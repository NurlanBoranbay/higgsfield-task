"""Correctness metric — hard assertions + LLM judge.

Registered as ``@metric("correctness")``.  Checks deterministic
assertions first (fast / free), then invokes the LLM judge only if
those pass.
"""

from __future__ import annotations

from typing import Any

from eval.judge import build_trace_summary, judge
from eval.metrics import MetricPlugin, metric
from eval.models import JudgeVerdict, MetricResult, TestCase


@metric("correctness")
class CorrectnessMetric(MetricPlugin):
    """Factual accuracy: hard substring / stopped-reason checks + LLM judge."""

    def score(self, trace: dict[str, Any], test_case: TestCase) -> MetricResult:
        answer = trace.get("final_answer", "") or ""
        citations = trace.get("citations", [])
        stopped = trace.get("stopped_reason", "")
        details: dict[str, Any] = {}
        failures: list[str] = []

        # ── Hard assertions ────────────────────────────────────────
        for ha in test_case.hard_assertions:
            if ha.type == "answer_contains":
                substr = str(ha.value).lower()
                if substr not in answer.lower():
                    failures.append(f"answer_contains: expected '{ha.value}'")

            elif ha.type == "answer_not_contains":
                substr = str(ha.value).lower()
                if substr in answer.lower():
                    failures.append(
                        f"answer_not_contains: found forbidden '{ha.value}'"
                    )

            elif ha.type == "stopped_reason_is":
                if stopped != ha.value:
                    failures.append(
                        f"stopped_reason_is: expected '{ha.value}', got '{stopped}'"
                    )

            elif ha.type == "citations_include":
                if str(ha.value) not in citations:
                    failures.append(f"citations_include: missing '{ha.value}'")

            elif ha.type == "citations_not_include":
                if str(ha.value) in citations:
                    failures.append(
                        f"citations_not_include: found forbidden '{ha.value}'"
                    )

        details["hard_failures"] = failures

        if failures:
            return MetricResult(
                metric_name="correctness",
                passed=False,
                score=0.0,
                rationale="; ".join(failures),
                details=details,
            )

        # ── LLM judge (soft) ──────────────────────────────────────
        # Only run for cases that declare soft correctness assertions
        soft_correctness = [
            sa for sa in test_case.soft_assertions if sa.type == "correctness"
        ]
        if not soft_correctness:
            # No soft check — hard-only pass
            return MetricResult(
                metric_name="correctness",
                passed=True,
                score=1.0,
                rationale="All hard assertions passed; no soft check required.",
                details=details,
            )

        # Check for cached verdict during rescore
        cached = trace.get("_cached_verdicts", {}).get("correctness")
        if trace.get("_rescore") and cached:
            verdict = JudgeVerdict(**cached)
        else:
            sa = soft_correctness[0]
            expected = sa.expected or test_case.expected_answer_summary or ""
            corpus_ctx = test_case.corpus_context or ""

            verdict = judge(
                rubric_name="correctness",
                question=test_case.input,
                answer=answer,
                citations=citations,
                trace_summary=build_trace_summary(trace),
                expected=expected,
                corpus_context=corpus_ctx,
                rubric_override=sa.rubric_override or "",
            )
            # Cache for future rescores
            trace.setdefault("_cached_verdicts", {})["correctness"] = verdict.model_dump()

        details["judge_verdict"] = verdict.model_dump()
        return MetricResult(
            metric_name="correctness",
            passed=verdict.passed,
            score=verdict.score,
            rationale=verdict.rationale,
            details=details,
        )
