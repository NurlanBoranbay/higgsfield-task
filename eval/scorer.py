"""Scorer — thin orchestration layer.

Discovers registered metric plugins and runs each against a trace.
Does NOT contain any metric logic — that lives in ``eval/metrics/``.
"""

from __future__ import annotations

from typing import Any

from eval.metrics import get_all_metrics
from eval.models import CaseResult, TestCase


def score_case(
    trace: dict[str, Any],
    test_case: TestCase,
    run_id: str,
    rescore: bool = False,
) -> CaseResult:
    """Score a single trace against its test case using all registered metrics.

    When ``rescore=True``, the scorer signals metric plugins to reuse any
    cached judge verdicts already stored in the trace (via the
    ``_rescore`` key in the trace dict) rather than calling the LLM again.

    Returns a ``CaseResult`` with per-metric results and an overall pass/fail.
    """
    if rescore:
        trace["_rescore"] = True
    else:
        trace.pop("_rescore", None)

    metrics = get_all_metrics()
    results = []

    for _name, plugin in metrics.items():
        result = plugin.score(trace, test_case)
        results.append(result)

    overall_pass = all(r.passed for r in results)
    failure_reasons = [r.rationale for r in results if not r.passed]

    return CaseResult(
        test_case_id=test_case.id,
        run_id=run_id,
        passed=overall_pass,
        metric_results=results,
        failure_reasons=failure_reasons,
        trace=trace,
    )
