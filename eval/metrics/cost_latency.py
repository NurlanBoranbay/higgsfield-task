"""Cost & latency metric.

Registered as ``@metric("cost_latency")``.  Extracts cost, latency,
and token counts from the trace and checks against optional thresholds.
Always reports the raw numbers regardless of whether thresholds are set.
"""

from __future__ import annotations

from typing import Any

from eval.metrics import MetricPlugin, metric
from eval.models import MetricResult, TestCase


@metric("cost_latency")
class CostLatencyMetric(MetricPlugin):
    """Evaluate cost and latency of the agent run."""

    def score(self, trace: dict[str, Any], test_case: TestCase) -> MetricResult:
        cfg = test_case.metric_config
        cost = trace.get("cost_usd", 0.0)
        latency = trace.get("wall_time_ms", 0)
        tokens = trace.get("total_tokens", {"input": 0, "output": 0})

        failures: list[str] = []
        details: dict[str, Any] = {
            "cost_usd": cost,
            "wall_time_ms": latency,
            "input_tokens": tokens.get("input", 0),
            "output_tokens": tokens.get("output", 0),
        }

        # ── Threshold checks ──────────────────────────────────────
        if cfg.max_cost_usd is not None and cost > cfg.max_cost_usd:
            failures.append(
                f"cost exceeded: ${cost:.4f} > ${cfg.max_cost_usd:.4f}"
            )

        if cfg.max_latency_ms is not None and latency > cfg.max_latency_ms:
            failures.append(
                f"latency exceeded: {latency}ms > {cfg.max_latency_ms}ms"
            )

        # ── Score ─────────────────────────────────────────────────
        if failures:
            # Proportional penalty: score = threshold / actual (clamped to [0, 1])
            penalty_scores: list[float] = []
            if cfg.max_cost_usd is not None and cost > cfg.max_cost_usd:
                penalty_scores.append(cfg.max_cost_usd / max(cost, 1e-9))
            if cfg.max_latency_ms is not None and latency > cfg.max_latency_ms:
                penalty_scores.append(cfg.max_latency_ms / max(latency, 1))
            score = min(penalty_scores) if penalty_scores else 0.5
            score = max(0.0, min(1.0, score))
        else:
            score = 1.0

        details["failures"] = failures
        return MetricResult(
            metric_name="cost_latency",
            passed=len(failures) == 0,
            score=score,
            rationale=(
                "; ".join(failures)
                if failures
                else f"Within budget: ${cost:.4f}, {latency}ms"
            ),
            details=details,
        )
