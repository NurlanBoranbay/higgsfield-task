"""Data models for the evaluation framework.

All structured data flows through these Pydantic models — test cases loaded
from YAML, metric results produced by plugins, case-level and run-level
reports, and LLM-judge verdicts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Test-case definition (loaded from YAML)
# ---------------------------------------------------------------------------


class HardAssertion(BaseModel):
    """A single deterministic check declared in a test case."""

    type: str  # e.g. "answer_contains", "tool_was_called", "stopped_reason_is"
    value: Any  # argument — string, int, list, depending on type


class SoftAssertion(BaseModel):
    """An LLM-judge check declared in a test case."""

    type: str  # e.g. "correctness", "safety"
    rubric_override: Optional[str] = None  # optional per-case rubric addition
    expected: Optional[str] = None  # expected behaviour description for judge


class MetricConfig(BaseModel):
    """Per-case thresholds / config for specific metrics."""

    max_tool_calls: Optional[int] = None
    required_tools: Optional[list[str]] = None
    forbidden_tools: Optional[list[str]] = None
    required_tool_sequence: Optional[list[str]] = None
    max_cost_usd: Optional[float] = None
    max_latency_ms: Optional[int] = None
    expected_citations: Optional[list[str]] = None
    forbidden_citations: Optional[list[str]] = None


class TestCase(BaseModel):
    """A single evaluation case loaded from YAML."""

    id: str
    description: str
    category: str  # happy_path, ambiguous, refusal, adversarial, etc.
    input: str  # the question sent to the agent
    hard_assertions: list[HardAssertion] = Field(default_factory=list)
    soft_assertions: list[SoftAssertion] = Field(default_factory=list)
    metric_config: MetricConfig = Field(default_factory=MetricConfig)
    expected_answer_summary: Optional[str] = None  # for judge context
    corpus_context: Optional[str] = None  # relevant corpus info for judge


# ---------------------------------------------------------------------------
# Metric + scoring results
# ---------------------------------------------------------------------------


class MetricResult(BaseModel):
    """Result from a single metric plugin for a single case."""

    metric_name: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    rationale: str
    details: dict[str, Any] = Field(default_factory=dict)


class JudgeVerdict(BaseModel):
    """Structured output from the LLM judge."""

    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    rationale: str


class CaseResult(BaseModel):
    """Complete evaluation result for a single test case."""

    test_case_id: str
    run_id: str
    passed: bool
    metric_results: list[MetricResult]
    failure_reasons: list[str] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Run-level report
# ---------------------------------------------------------------------------


class RepeatResult(BaseModel):
    """Results for a single case across multiple repeats."""

    test_case_id: str
    total_runs: int
    passed_runs: int
    results: list[CaseResult]


class AggregateStats(BaseModel):
    """Aggregate statistics for a full eval run."""

    total_cases: int
    passed_cases: int
    pass_rate: float
    total_cost_usd: float
    p50_latency_ms: float
    p95_latency_ms: float
    mean_tool_calls: float


class CaseDiff(BaseModel):
    """Diff for a single case between two runs."""

    test_case_id: str
    previous_passed: bool
    current_passed: bool
    is_regression: bool
    metric_diffs: dict[str, dict[str, Any]] = Field(default_factory=dict)


class EvalRun(BaseModel):
    """A complete evaluation run."""

    run_id: str
    timestamp: str
    model: str
    repeats: int = 1
    case_results: list[CaseResult] = Field(default_factory=list)
    repeat_results: list[RepeatResult] = Field(default_factory=list)
    aggregate: Optional[AggregateStats] = None
    diffs: list[CaseDiff] = Field(default_factory=list)
