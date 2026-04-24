"""Unit tests for the evaluation framework.

These tests validate the scorer, reporter, judge parsing, and metric
plugins using mock data — NO API calls required.  Run with:

    ./venv/bin/python -m pytest tests/ -v
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import pytest

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.models import (
    AggregateStats,
    CaseDiff,
    CaseResult,
    EvalRun,
    HardAssertion,
    JudgeVerdict,
    MetricConfig,
    MetricResult,
    RepeatResult,
    SoftAssertion,
    TestCase,
)


# ---------------------------------------------------------------------------
# Fixtures — reusable mock data
# ---------------------------------------------------------------------------


def _make_trace(
    answer: str = "The answer is 42.",
    citations: list[str] | None = None,
    stopped_reason: str = "finish",
    cost: float = 0.005,
    latency: int = 3000,
    tool_calls: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a minimal mock trace."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a research agent."},
        {"role": "user", "content": "What is the answer?"},
    ]
    if tool_calls:
        messages.append({
            "role": "assistant",
            "text": "",
            "tool_calls": tool_calls,
            "latency_ms": 500,
        })
    return {
        "question": "What is the answer?",
        "final_answer": answer,
        "citations": citations or [],
        "stopped_reason": stopped_reason,
        "cost_usd": cost,
        "wall_time_ms": latency,
        "total_tokens": {"input": 1000, "output": 200},
        "messages": messages,
    }


def _make_test_case(
    case_id: str = "test_case",
    input_text: str = "What is the answer?",
    hard_assertions: list[dict] | None = None,
    soft_assertions: list[dict] | None = None,
    metric_config: dict | None = None,
) -> TestCase:
    """Build a test case from simple dicts."""
    return TestCase(
        id=case_id,
        description="Test case",
        category="test",
        input=input_text,
        hard_assertions=[
            HardAssertion(**a) for a in (hard_assertions or [])
        ],
        soft_assertions=[
            SoftAssertion(**a) for a in (soft_assertions or [])
        ],
        metric_config=MetricConfig(**(metric_config or {})),
    )


# ---------------------------------------------------------------------------
# Test: Judge parsing (_parse_verdict)
# ---------------------------------------------------------------------------


class TestJudgeParsing:
    """Test the _parse_verdict function handles edge cases."""

    def test_valid_json(self):
        from eval.judge import _parse_verdict
        raw = '{"passed": true, "score": 0.85, "rationale": "Good answer"}'
        v = _parse_verdict(raw)
        assert v.passed is True
        assert v.score == 0.85
        assert "Good answer" in v.rationale

    def test_markdown_fenced_json(self):
        from eval.judge import _parse_verdict
        raw = '```json\n{"passed": false, "score": 0.3, "rationale": "Bad"}\n```'
        v = _parse_verdict(raw)
        assert v.passed is False
        assert v.score == 0.3

    def test_malformed_json_fails_safely(self):
        from eval.judge import _parse_verdict
        v = _parse_verdict("this is not json at all")
        assert v.passed is False
        assert v.score == 0.0
        assert "could not be parsed" in v.rationale

    def test_empty_string(self):
        from eval.judge import _parse_verdict
        v = _parse_verdict("")
        assert v.passed is False
        assert v.score == 0.0

    def test_missing_fields_default_safely(self):
        from eval.judge import _parse_verdict
        raw = '{"score": 0.5}'
        v = _parse_verdict(raw)
        assert v.passed is False  # default
        assert v.score == 0.5


# ---------------------------------------------------------------------------
# Test: Metric plugins (deterministic checks only)
# ---------------------------------------------------------------------------


class TestCorrectnessHardAssertions:
    """Test hard assertion checks in the correctness metric."""

    def test_answer_contains_pass(self):
        from eval.metrics.correctness import CorrectnessMetric
        metric = CorrectnessMetric()
        trace = _make_trace(answer="The year was 2012.")
        tc = _make_test_case(hard_assertions=[
            {"type": "answer_contains", "value": "2012"},
        ])
        result = metric.score(trace, tc)
        assert result.passed is True
        assert result.score == 1.0

    def test_answer_contains_fail(self):
        from eval.metrics.correctness import CorrectnessMetric
        metric = CorrectnessMetric()
        trace = _make_trace(answer="The year was 2013.")
        tc = _make_test_case(hard_assertions=[
            {"type": "answer_contains", "value": "2012"},
        ])
        result = metric.score(trace, tc)
        assert result.passed is False
        assert result.score == 0.0

    def test_stopped_reason_check(self):
        from eval.metrics.correctness import CorrectnessMetric
        metric = CorrectnessMetric()
        trace = _make_trace(stopped_reason="max_steps")
        tc = _make_test_case(hard_assertions=[
            {"type": "stopped_reason_is", "value": "finish"},
        ])
        result = metric.score(trace, tc)
        assert result.passed is False
        assert "stopped_reason_is" in result.rationale

    def test_answer_not_contains_pass(self):
        from eval.metrics.correctness import CorrectnessMetric
        metric = CorrectnessMetric()
        trace = _make_trace(answer="The rover is powered by RTG.")
        tc = _make_test_case(hard_assertions=[
            {"type": "answer_not_contains", "value": "solar panels"},
        ])
        result = metric.score(trace, tc)
        assert result.passed is True

    def test_answer_not_contains_fail(self):
        from eval.metrics.correctness import CorrectnessMetric
        metric = CorrectnessMetric()
        trace = _make_trace(answer="It uses solar panels.")
        tc = _make_test_case(hard_assertions=[
            {"type": "answer_not_contains", "value": "solar panels"},
        ])
        result = metric.score(trace, tc)
        assert result.passed is False

    def test_citations_include(self):
        from eval.metrics.correctness import CorrectnessMetric
        metric = CorrectnessMetric()
        trace = _make_trace(citations=["https://example.com/page1"])
        tc = _make_test_case(hard_assertions=[
            {"type": "citations_include", "value": "https://example.com/page1"},
        ])
        result = metric.score(trace, tc)
        assert result.passed is True

    def test_citations_not_include_fail(self):
        from eval.metrics.correctness import CorrectnessMetric
        metric = CorrectnessMetric()
        trace = _make_trace(citations=["https://corpus.local/secret"])
        tc = _make_test_case(hard_assertions=[
            {"type": "citations_not_include", "value": "https://corpus.local/secret"},
        ])
        result = metric.score(trace, tc)
        assert result.passed is False


class TestToolEfficiency:
    """Test the tool_efficiency metric plugin."""

    def test_required_tools_pass(self):
        from eval.metrics.tool_efficiency import ToolEfficiencyMetric
        metric = ToolEfficiencyMetric()
        trace = _make_trace(tool_calls=[
            {"name": "web_search", "args": {"query": "test"}, "id": "1"},
            {"name": "fetch_url", "args": {"url": "http://x"}, "id": "2"},
        ])
        tc = _make_test_case(metric_config={
            "required_tools": ["web_search", "fetch_url"],
        })
        result = metric.score(trace, tc)
        assert result.passed is True

    def test_required_tools_fail(self):
        from eval.metrics.tool_efficiency import ToolEfficiencyMetric
        metric = ToolEfficiencyMetric()
        trace = _make_trace(tool_calls=[
            {"name": "web_search", "args": {"query": "test"}, "id": "1"},
        ])
        tc = _make_test_case(metric_config={
            "required_tools": ["web_search", "fetch_url"],
        })
        result = metric.score(trace, tc)
        assert result.passed is False
        assert "fetch_url" in result.rationale

    def test_max_tool_calls_exceeded(self):
        from eval.metrics.tool_efficiency import ToolEfficiencyMetric
        metric = ToolEfficiencyMetric()
        trace = _make_trace(tool_calls=[
            {"name": f"web_search", "args": {"query": f"q{i}"}, "id": str(i)}
            for i in range(6)
        ])
        tc = _make_test_case(metric_config={"max_tool_calls": 5})
        result = metric.score(trace, tc)
        assert result.passed is False
        assert "too many" in result.rationale

    def test_forbidden_tools(self):
        from eval.metrics.tool_efficiency import ToolEfficiencyMetric
        metric = ToolEfficiencyMetric()
        trace = _make_trace(tool_calls=[
            {"name": "web_search", "args": {}, "id": "1"},
            {"name": "dangerous_tool", "args": {}, "id": "2"},
        ])
        tc = _make_test_case(metric_config={
            "forbidden_tools": ["dangerous_tool"],
        })
        result = metric.score(trace, tc)
        assert result.passed is False

    def test_cited_url_not_fetched(self):
        from eval.metrics.tool_efficiency import ToolEfficiencyMetric
        metric = ToolEfficiencyMetric()
        trace = _make_trace(
            citations=["https://example.com/unfetched"],
            tool_calls=[
                {"name": "fetch_url", "args": {"url": "https://example.com/fetched"}, "id": "1"},
            ],
        )
        tc = _make_test_case()
        result = metric.score(trace, tc)
        assert result.passed is False
        assert "cited URL not fetched" in result.rationale


class TestCostLatency:
    """Test the cost_latency metric plugin."""

    def test_within_budget(self):
        from eval.metrics.cost_latency import CostLatencyMetric
        metric = CostLatencyMetric()
        trace = _make_trace(cost=0.005, latency=3000)
        tc = _make_test_case(metric_config={
            "max_cost_usd": 0.01,
            "max_latency_ms": 5000,
        })
        result = metric.score(trace, tc)
        assert result.passed is True
        assert result.score == 1.0

    def test_cost_exceeded_proportional(self):
        from eval.metrics.cost_latency import CostLatencyMetric
        metric = CostLatencyMetric()
        trace = _make_trace(cost=0.02, latency=3000)
        tc = _make_test_case(metric_config={
            "max_cost_usd": 0.01,
        })
        result = metric.score(trace, tc)
        assert result.passed is False
        # Proportional: 0.01 / 0.02 = 0.5
        assert result.score == pytest.approx(0.5, abs=0.01)

    def test_no_thresholds_always_passes(self):
        from eval.metrics.cost_latency import CostLatencyMetric
        metric = CostLatencyMetric()
        trace = _make_trace(cost=100.0, latency=999999)
        tc = _make_test_case()
        result = metric.score(trace, tc)
        assert result.passed is True


class TestSafetyHardChecks:
    """Test deterministic safety checks (no LLM judge)."""

    def test_word_count_pass(self):
        from eval.metrics.safety import SafetyMetric
        metric = SafetyMetric()
        trace = _make_trace(answer=" ".join(["word"] * 100))
        tc = _make_test_case()  # no soft assertions
        result = metric.score(trace, tc)
        # Should pass the word count check
        assert result.details.get("word_count", 0) <= 120

    def test_word_count_fail(self):
        from eval.metrics.safety import SafetyMetric
        metric = SafetyMetric()
        trace = _make_trace(answer=" ".join(["word"] * 150))
        tc = _make_test_case()  # no soft assertions
        result = metric.score(trace, tc)
        assert result.passed is False
        assert "too long" in result.rationale

    def test_forbidden_citation_auto_zero(self):
        from eval.metrics.safety import SafetyMetric
        metric = SafetyMetric()
        trace = _make_trace(citations=["https://corpus.local/secret"])
        tc = _make_test_case(metric_config={
            "forbidden_citations": ["https://corpus.local/secret"],
        })
        result = metric.score(trace, tc)
        assert result.passed is False
        assert result.score == 0.0  # critical violation forces 0.0


class TestGrounding:
    """Test the grounding metric plugin."""

    def test_no_extract_calls(self):
        from eval.metrics.grounding import GroundingMetric
        metric = GroundingMetric()
        trace = _make_trace()
        tc = _make_test_case()
        result = metric.score(trace, tc)
        assert result.passed is True
        assert "N/A" in result.rationale

    def test_verbatim_quotes_pass(self):
        from eval.metrics.grounding import GroundingMetric
        metric = GroundingMetric()
        source_text = "Chlorophyll absorbs light, driving the splitting of water."
        trace = _make_trace()
        trace["messages"] = [
            {"role": "assistant", "text": "", "tool_calls": [
                {"id": "tc1", "name": "extract_quotes", "args": {
                    "text": source_text,
                    "topic": "chlorophyll",
                }},
            ], "latency_ms": 100},
            {"role": "tool", "name": "extract_quotes", "tool_use_id": "tc1",
             "content": ["Chlorophyll absorbs light, driving the splitting of water."]},
        ]
        tc = _make_test_case()
        result = metric.score(trace, tc)
        assert result.passed is True
        assert result.score == 1.0

    def test_hallucinated_quotes_fail(self):
        from eval.metrics.grounding import GroundingMetric
        metric = GroundingMetric()
        source_text = "The sky is blue because of Rayleigh scattering."
        trace = _make_trace()
        trace["messages"] = [
            {"role": "assistant", "text": "", "tool_calls": [
                {"id": "tc1", "name": "extract_quotes", "args": {
                    "text": source_text,
                    "topic": "sky color",
                }},
            ], "latency_ms": 100},
            {"role": "tool", "name": "extract_quotes", "tool_use_id": "tc1",
             "content": ["The sky appears blue due to the way molecules scatter sunlight."]},
        ]
        tc = _make_test_case()
        result = metric.score(trace, tc)
        assert result.passed is False
        assert result.score < 1.0


# ---------------------------------------------------------------------------
# Test: Reporter (aggregation, diffing)
# ---------------------------------------------------------------------------


class TestReporterAggregation:
    """Test aggregate stats computation."""

    def test_compute_aggregate(self):
        from eval.reporter import _compute_aggregate

        results = [
            CaseResult(
                test_case_id=f"case_{i}",
                run_id="test",
                passed=i < 3,
                metric_results=[],
                trace=_make_trace(cost=0.01 * (i + 1), latency=1000 * (i + 1)),
            )
            for i in range(5)
        ]
        agg = _compute_aggregate(results)
        assert agg.total_cases == 5
        assert agg.passed_cases == 3
        assert agg.pass_rate == 0.6
        assert agg.total_cost_usd > 0

    def test_diff_finds_regressions(self):
        from eval.reporter import _diff_runs

        prev = [
            CaseResult(
                test_case_id="case_1",
                run_id="prev",
                passed=True,
                metric_results=[MetricResult(
                    metric_name="correctness", passed=True, score=0.9, rationale="ok",
                )],
                trace={},
            ),
        ]
        curr = [
            CaseResult(
                test_case_id="case_1",
                run_id="curr",
                passed=False,
                metric_results=[MetricResult(
                    metric_name="correctness", passed=False, score=0.3, rationale="bad",
                )],
                trace={},
            ),
        ]
        diffs = _diff_runs(curr, prev)
        assert len(diffs) == 1
        assert diffs[0].is_regression is True
        assert diffs[0].metric_diffs["correctness"]["delta"] == pytest.approx(-0.6, abs=0.01)


# ---------------------------------------------------------------------------
# Test: Scorer orchestration
# ---------------------------------------------------------------------------


class TestScorer:
    """Test the scorer orchestration layer."""

    def test_overall_pass_requires_all_metrics(self):
        from eval.scorer import score_case
        trace = _make_trace(answer="2012", stopped_reason="finish")
        tc = _make_test_case(hard_assertions=[
            {"type": "answer_contains", "value": "2012"},
            {"type": "stopped_reason_is", "value": "finish"},
        ])
        # This will run all metric plugins.
        # With no soft assertions, correctness should pass.
        result = score_case(trace, tc, "test_run")
        # At minimum, hard assertions should pass
        corr = next(
            (m for m in result.metric_results if m.metric_name == "correctness"),
            None,
        )
        assert corr is not None
        assert corr.passed is True


# ---------------------------------------------------------------------------
# Test: Model validation
# ---------------------------------------------------------------------------


class TestModels:
    """Test Pydantic model validation."""

    def test_metric_result_score_bounds(self):
        with pytest.raises(Exception):
            MetricResult(
                metric_name="test", passed=True, score=1.5, rationale="bad"
            )

    def test_test_case_from_dict(self):
        tc = TestCase(
            id="test",
            description="desc",
            category="happy_path",
            input="question",
        )
        assert tc.hard_assertions == []
        assert tc.metric_config.max_tool_calls is None

    def test_eval_run_serialization(self):
        run = EvalRun(
            run_id="abc123",
            timestamp="2024-01-01T00:00:00Z",
            model="test-model",
        )
        data = run.model_dump()
        assert data["run_id"] == "abc123"
        restored = EvalRun(**data)
        assert restored.run_id == run.run_id


# ---------------------------------------------------------------------------
# Test: Trace summary builder
# ---------------------------------------------------------------------------


class TestTraceSummary:
    """Test the trace summary builder."""

    def test_basic_trace_summary(self):
        from eval.judge import build_trace_summary
        trace = _make_trace(tool_calls=[
            {"name": "web_search", "args": {"query": "test"}, "id": "1"},
        ])
        summary = build_trace_summary(trace)
        assert "web_search" in summary
        assert "User" in summary

    def test_error_trace_summary(self):
        from eval.judge import build_trace_summary
        trace = _make_trace()
        trace["error"] = "APIError: rate limit exceeded"
        summary = build_trace_summary(trace)
        assert "rate limit" in summary
