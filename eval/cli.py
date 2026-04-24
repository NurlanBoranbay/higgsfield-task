"""CLI for the evaluation framework.

Usage:
    python run_eval.py                           # Run full suite
    python run_eval.py --case voyager_heliopause  # Run single case
    python run_eval.py --repeats 3                # Flakiness detection
    python run_eval.py --concurrency 5            # Set parallelism
    python run_eval.py --rescore --run-id abc123  # Re-score cached traces
    python run_eval.py --diff abc123              # Diff against previous
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from eval.models import TestCase, HardAssertion, SoftAssertion, MetricConfig
from eval.runner import run_suite, rescore_traces
from eval.reporter import build_report, save_report, print_report, load_report
from eval.viewer import generate_viewer
from eval.models import EvalRun


PROJECT_ROOT = Path(__file__).parent.parent  # higgs/
SUITE_PATH = PROJECT_ROOT / "test_suite" / "cases.yaml"
REPORTS_DIR = PROJECT_ROOT / "reports"
TRACES_DIR = PROJECT_ROOT / "traces"
FIXTURE_TRACES_DIR = PROJECT_ROOT / "fixture_traces"


def _load_test_cases(suite_path: Path) -> list[TestCase]:
    """Load test cases from YAML file."""
    with suite_path.open() as f:
        data = yaml.safe_load(f)

    cases: list[TestCase] = []
    for raw in data.get("cases", []):
        hard = [HardAssertion(**a) for a in raw.get("hard_assertions", [])]
        soft = [SoftAssertion(**a) for a in raw.get("soft_assertions", [])]
        mc_raw = raw.get("metric_config", {})
        mc = MetricConfig(**mc_raw) if mc_raw else MetricConfig()

        cases.append(
            TestCase(
                id=raw["id"],
                description=raw.get("description", ""),
                category=raw.get("category", ""),
                input=raw["input"],
                hard_assertions=hard,
                soft_assertions=soft,
                metric_config=mc,
                expected_answer_summary=raw.get("expected_answer_summary"),
                corpus_context=raw.get("corpus_context"),
            )
        )
    return cases


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Deep Research Lite — Eval Framework")
    parser.add_argument("--case", type=str, help="Run a single case by ID")
    parser.add_argument("--repeats", type=int, default=1, help="Repeat each case N times")
    parser.add_argument("--concurrency", type=int, default=3, help="Max parallel runs")
    parser.add_argument("--rescore", action="store_true", help="Re-score cached traces")
    parser.add_argument("--run-id", type=str, help="Run ID for --rescore")
    parser.add_argument("--diff", type=str, help="Diff against a previous run ID")
    parser.add_argument("--suite", type=str, default=str(SUITE_PATH), help="Path to test suite YAML")

    args = parser.parse_args()

    # Load test cases
    suite_path = Path(args.suite)
    test_cases = _load_test_cases(suite_path)
    print(f" Loaded {len(test_cases)} test cases from {suite_path.name}")

    # Filter to single case if specified
    if args.case:
        test_cases = [tc for tc in test_cases if tc.id == args.case]
        if not test_cases:
            print(f" Case '{args.case}' not found", file=sys.stderr)
            return 1
        print(f"   Filtering to case: {args.case}")

    # ── Re-score mode ─────────────────────────────────────────
    if args.rescore:
        if not args.run_id:
            print(" --rescore requires --run-id", file=sys.stderr)
            return 1
        traces_search = TRACES_DIR
        if not (TRACES_DIR / args.run_id).exists():
            if (FIXTURE_TRACES_DIR / args.run_id).exists():
                traces_search = FIXTURE_TRACES_DIR
                print(f"   (using fixture traces from {FIXTURE_TRACES_DIR.name}/)")
            else:
                print(f" Run '{args.run_id}' not found in traces/ or fixture_traces/", file=sys.stderr)
                return 1
        case_results = rescore_traces(test_cases, args.run_id, traces_search)
        report = build_report(
            run_id=args.run_id,
            model="(rescore)",
            case_results=case_results,
        )
    else:
        # ── Normal run ────────────────────────────────────────
        run_id, case_results, repeat_results = run_suite(
            test_cases,
            concurrency=args.concurrency,
            repeats=args.repeats,
            traces_dir=TRACES_DIR,
        )

        # Load previous report for diffing
        previous_results = None
        if args.diff:
            prev_path = REPORTS_DIR / f"{args.diff}.json"
            if prev_path.exists():
                prev_report = load_report(prev_path)
                previous_results = prev_report.case_results
                print(f"\n Diffing against run {args.diff}")
            else:
                print(f"  Previous run {args.diff} not found, skipping diff")

        # Determine model from first trace
        model = "unknown"
        if case_results and case_results[0].trace:
            model = case_results[0].trace.get("model", "unknown")

        report = build_report(
            run_id=run_id,
            model=model,
            case_results=case_results,
            repeat_results=repeat_results,
            previous_results=previous_results,
            repeats=args.repeats,
        )

    # ── Save report ───────────────────────────────────────────
    report_path = save_report(report, REPORTS_DIR)
    print(f" Report saved: {report_path}")

    # ── Generate HTML viewer ──────────────────────────────────
    viewer_path = REPORTS_DIR / f"{report.run_id}_viewer.html"
    generate_viewer(report, viewer_path)
    print(f" Viewer:  {viewer_path}")

    # ── Print console report ──────────────────────────────────
    print_report(report)

    # Exit code: 0 if all pass, 1 if any fail
    if report.aggregate:
        return 0 if report.aggregate.pass_rate == 1.0 else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
