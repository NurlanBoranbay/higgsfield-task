"""Runner — executes the agent, captures traces, handles parallelism + retries.

Orchestrates running test cases through the agent, saving traces to
disk, and passing them to the scorer.  Supports ``--repeats N`` for
flakiness detection and ``--rescore`` for re-evaluating cached traces
without re-calling the agent.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Ensure the agent code is importable
_AGENT_DIR = Path(__file__).parent.parent / "higgsfield-deep-research-hometask"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from eval.models import CaseResult, RepeatResult, TestCase
from eval.scorer import score_case

TRACES_DIR = Path(__file__).parent.parent / "traces"
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds, doubles each retry


def _is_transient_error(error: str | None) -> bool:
    """Check if an error is transient (429, 5xx, network)."""
    if error is None:
        return False
    error_lower = error.lower()
    transient_patterns = [
        "429", "rate_limit", "rate limit",
        "500", "502", "503", "529",
        "overloaded",
        "connection", "timeout", "network",
    ]
    return any(pat in error_lower for pat in transient_patterns)


def _run_single(
    test_case: TestCase,
    run_id: str,
    traces_dir: Path,
) -> CaseResult:
    """Run the agent on a single test case with retry logic."""
    load_dotenv()

    # Import inside function to avoid loading corpus at import time
    from agent import run_agent

    last_error: str | None = None
    trace: dict[str, Any] | None = None

    # ── Step 1: Run the agent (retryable on transient errors) ──
    for attempt in range(MAX_RETRIES):
        try:
            result = run_agent(test_case.input)
            trace = result.to_dict()

            # Save trace to disk
            trace_path = traces_dir / run_id / f"{test_case.id}.json"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            with trace_path.open("w") as f:
                json.dump(trace, f, indent=2, default=str)

            break  # Agent ran successfully

        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            if _is_transient_error(last_error) and attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF * (2 ** attempt)
                print(
                    f"  Transient error on {test_case.id} "
                    f"(attempt {attempt + 1}), retrying in {wait:.0f}s: {last_error}"
                )
                time.sleep(wait)
                continue
            else:
                break

    # ── Step 2: Build error trace if agent failed ──────────────
    if trace is None:
        trace = {
            "run_id": run_id,
            "question": test_case.input,
            "final_answer": None,
            "citations": [],
            "stopped_reason": "error",
            "error": last_error,
            "total_tokens": {"input": 0, "output": 0},
            "cost_usd": 0.0,
            "wall_time_ms": 0,
            "messages": [],
        }

    # ── Step 3: Score (never retried) ──────────────────────────
    return score_case(trace, test_case, run_id)


def run_suite(
    test_cases: list[TestCase],
    concurrency: int = 3,
    repeats: int = 1,
    traces_dir: Path | None = None,
) -> tuple[str, list[CaseResult], list[RepeatResult]]:
    """Run all test cases and return results.

    Cases are run in parallel with a configurable concurrency cap.  When
    ``repeats > 1`` every (case × repeat) pair is submitted to the same
    pool so the concurrency limit governs *all* in-flight agent calls.

    Returns
    -------
    run_id : str
        Unique ID for this eval run.
    case_results : list[CaseResult]
        One result per case (or the first run if repeats > 1).
    repeat_results : list[RepeatResult]
        Per-case repeat stats (only meaningful when repeats > 1).
    """
    run_id = str(uuid.uuid4())[:8]
    if traces_dir is None:
        traces_dir = TRACES_DIR
    traces_dir.mkdir(parents=True, exist_ok=True)

    total = len(test_cases) * repeats
    completed = 0

    print(f"\n Starting eval run {run_id}")
    print(f"   {len(test_cases)} cases × {repeats} repeat(s) = {total} runs")
    print(f"   Concurrency: {concurrency}")
    print()

    # Submit all (case × repeat) pairs to one pool so the concurrency
    # cap governs total in-flight agent calls — no thundering herd.
    # Key: future -> (TestCase, repeat_index)
    future_to_info: dict[Any, tuple[TestCase, int]] = {}

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for tc in test_cases:
            for r in range(repeats):
                repeat_run_id = f"{run_id}_r{r}" if repeats > 1 else run_id
                future = executor.submit(
                    _run_single, tc, repeat_run_id, traces_dir
                )
                future_to_info[future] = (tc, r)

        # Collect results as they complete
        per_case_runs: dict[str, list[CaseResult]] = {
            tc.id: [] for tc in test_cases
        }

        for future in as_completed(future_to_info):
            tc, r = future_to_info[future]
            result = future.result()
            per_case_runs[tc.id].append(result)
            completed += 1
            status = "PASSED" if result.passed else "FAILED"
            label = f"[{r+1}/{repeats}]" if repeats > 1 else ""
            print(
                f"  {status} {tc.id} {label} "
                f"({completed}/{total})"
            )

    # Build outputs preserving original case order
    all_case_results: list[CaseResult] = []
    repeat_results: list[RepeatResult] = []

    for tc in test_cases:
        case_runs = per_case_runs[tc.id]
        # Store first run as the canonical result
        all_case_results.append(case_runs[0])

        if repeats > 1:
            passed_count = sum(1 for cr in case_runs if cr.passed)
            repeat_results.append(
                RepeatResult(
                    test_case_id=tc.id,
                    total_runs=repeats,
                    passed_runs=passed_count,
                    results=case_runs,
                )
            )

    return run_id, all_case_results, repeat_results


def rescore_traces(
    test_cases: list[TestCase],
    run_id: str,
    traces_dir: Path | None = None,
) -> list[CaseResult]:
    """Re-score cached traces without re-running the agent."""
    if traces_dir is None:
        traces_dir = TRACES_DIR

    results: list[CaseResult] = []
    trace_run_dir = traces_dir / run_id

    print(f"\n Re-scoring traces from run {run_id}")

    for tc in test_cases:
        trace_path = trace_run_dir / f"{tc.id}.json"
        if not trace_path.exists():
            print(f"    No trace found for {tc.id}, skipping")
            continue

        with trace_path.open() as f:
            trace = json.load(f)

        result = score_case(trace, tc, run_id, rescore=True)
        status = "PASSED" if result.passed else "FAILED"
        print(f"  {status} {tc.id}")
        results.append(result)

    return results
