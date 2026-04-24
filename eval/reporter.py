"""Reporter — generates run reports with aggregates and diffs.

Produces both a JSON report (machine-readable) and a console table
(human-readable).  Supports diffing against a previous run to surface
regressions.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.models import (
    AggregateStats,
    CaseDiff,
    CaseResult,
    EvalRun,
    RepeatResult,
)


def _compute_aggregate(case_results: list[CaseResult]) -> AggregateStats:
    """Compute aggregate statistics from case results."""
    total = len(case_results)
    passed = sum(1 for r in case_results if r.passed)

    costs = [r.trace.get("cost_usd", 0.0) for r in case_results]
    latencies = [r.trace.get("wall_time_ms", 0) for r in case_results]
    tool_counts = []
    for r in case_results:
        count = sum(
            len(m.get("tool_calls", []))
            for m in r.trace.get("messages", [])
            if m.get("role") == "assistant"
        )
        tool_counts.append(count)

    # p50 / p95 latency
    sorted_lat = sorted(latencies)
    p50 = sorted_lat[len(sorted_lat) // 2] if sorted_lat else 0.0
    p95_idx = int(len(sorted_lat) * 0.95)
    p95 = sorted_lat[min(p95_idx, len(sorted_lat) - 1)] if sorted_lat else 0.0

    return AggregateStats(
        total_cases=total,
        passed_cases=passed,
        pass_rate=round(passed / max(total, 1), 4),
        total_cost_usd=round(sum(costs), 6),
        p50_latency_ms=p50,
        p95_latency_ms=p95,
        mean_tool_calls=round(statistics.mean(tool_counts), 2) if tool_counts else 0.0,
    )


def _diff_runs(
    current: list[CaseResult], previous: list[CaseResult]
) -> list[CaseDiff]:
    """Compare current vs previous run results."""
    prev_map = {r.test_case_id: r for r in previous}
    diffs: list[CaseDiff] = []

    for curr in current:
        prev = prev_map.get(curr.test_case_id)
        if prev is None:
            continue

        # Build metric-level diffs
        metric_diffs: dict[str, dict[str, Any]] = {}
        prev_metrics = {m.metric_name: m for m in prev.metric_results}
        for m in curr.metric_results:
            pm = prev_metrics.get(m.metric_name)
            if pm:
                metric_diffs[m.metric_name] = {
                    "prev_score": pm.score,
                    "curr_score": m.score,
                    "prev_passed": pm.passed,
                    "curr_passed": m.passed,
                    "delta": round(m.score - pm.score, 4),
                }

        diffs.append(
            CaseDiff(
                test_case_id=curr.test_case_id,
                previous_passed=prev.passed,
                current_passed=curr.passed,
                is_regression=prev.passed and not curr.passed,
                metric_diffs=metric_diffs,
            )
        )

    return diffs


def build_report(
    run_id: str,
    model: str,
    case_results: list[CaseResult],
    repeat_results: list[RepeatResult] | None = None,
    previous_results: list[CaseResult] | None = None,
    repeats: int = 1,
) -> EvalRun:
    """Build a complete evaluation report."""
    aggregate = _compute_aggregate(case_results)
    diffs = _diff_runs(case_results, previous_results) if previous_results else []

    return EvalRun(
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        model=model,
        repeats=repeats,
        case_results=case_results,
        repeat_results=repeat_results or [],
        aggregate=aggregate,
        diffs=diffs,
    )


def save_report(report: EvalRun, reports_dir: Path) -> Path:
    """Save report to disk as JSON."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{report.run_id}.json"
    with report_path.open("w") as f:
        json.dump(report.model_dump(), f, indent=2, default=str)
    return report_path


def load_report(report_path: Path) -> EvalRun:
    """Load a previously saved report."""
    with report_path.open() as f:
        data = json.load(f)
    return EvalRun(**data)


def print_report(report: EvalRun) -> None:
    """Print a human-readable report to console."""
    agg = report.aggregate
    if not agg:
        print("No aggregate stats available.")
        return

    print("\n" + "=" * 70)
    print(f"  EVAL RUN: {report.run_id}")
    # Format timestamp for readability
    try:
        dt = datetime.fromisoformat(report.timestamp.replace("Z", "+00:00"))
        formatted_ts = dt.strftime("%b %d, %Y at %H:%M UTC")
    except (ValueError, AttributeError):
        formatted_ts = report.timestamp
    print(f"  Model: {report.model}  |  Time: {formatted_ts}")
    print("=" * 70)

    # ── Per-case results ───────────────────────────────────────
    print(f"\n{'Case':<35} {'Result':<8} {'Correctness':<13} {'Tools':<8} {'Cost':<10} {'Safety':<8}")
    print("-" * 82)

    for cr in report.case_results:
        status = " PASS" if cr.passed else "❌ FAIL"
        metrics = {m.metric_name: m for m in cr.metric_results}

        corr = metrics.get("correctness")
        tool = metrics.get("tool_efficiency")
        cost = metrics.get("cost_latency")
        safe = metrics.get("safety")

        corr_s = f"{corr.score:.2f}" if corr else "-"
        tool_s = f"{tool.score:.2f}" if tool else "-"
        cost_s = f"${cr.trace.get('cost_usd', 0):.4f}" if cr.trace else "-"
        safe_s = f"{safe.score:.2f}" if safe else "-"

        print(f"  {cr.test_case_id:<33} {status:<8} {corr_s:<13} {tool_s:<8} {cost_s:<10} {safe_s:<8}")

        if not cr.passed:
            for reason in cr.failure_reasons[:2]:
                print(f"    └─ {reason[:80]}")

    # ── Repeat results ─────────────────────────────────────────
    if report.repeat_results:
        print(f"\n{'Case':<35} {'Pass Rate':<15}")
        print("-" * 50)
        for rr in report.repeat_results:
            print(f"  {rr.test_case_id:<33} {rr.passed_runs}/{rr.total_runs}")
            if rr.total_runs > 1:
                metrics_dict = {}
                for cr in rr.results:
                    for m in cr.metric_results:
                        metrics_dict.setdefault(m.metric_name, []).append(m.score)
                for m_name, scores in metrics_dict.items():
                    if len(scores) > 1:
                        variance = statistics.pvariance(scores)
                        mean_val = statistics.mean(scores)
                        print(f"    └─ {m_name:<15} mean={mean_val:.2f}, var={variance:.4f}")


    # ── Aggregate ──────────────────────────────────────────────
    print("\n" + "-" * 70)
    print(f"  Pass rate:     {agg.passed_cases}/{agg.total_cases} ({agg.pass_rate:.0%})")
    print(f"  Total cost:    ${agg.total_cost_usd:.4f}")
    print(f"  Latency:       p50={agg.p50_latency_ms:.0f}ms  p95={agg.p95_latency_ms:.0f}ms")
    print(f"  Tool calls:    mean={agg.mean_tool_calls:.1f} per case")
    print("-" * 70)

    # ── Diffs ──────────────────────────────────────────────────
    if report.diffs:
        regressions = [d for d in report.diffs if d.is_regression]
        improvements = [d for d in report.diffs if not d.is_regression and d.current_passed and not d.previous_passed]

        if regressions:
            print(f"\n  REGRESSIONS ({len(regressions)}):")
            for d in regressions:
                print(f"   {d.test_case_id}: PASS → FAIL")
                for name, md in d.metric_diffs.items():
                    if md.get("prev_passed") and not md.get("curr_passed"):
                        print(f"     └─ {name}: {md['prev_score']:.2f} → {md['curr_score']:.2f}")

        if improvements:
            print(f"\n IMPROVEMENTS ({len(improvements)}):")
            for d in improvements:
                print(f"   {d.test_case_id}: FAIL → PASS")

    print()
