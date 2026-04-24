"""Tool efficiency metric.

Registered as ``@metric("tool_efficiency")``.  Evaluates whether the
agent used tools effectively — no missing required tools, no unnecessary
calls, correct tool sequences, and citation integrity.
"""

from __future__ import annotations

from typing import Any

from eval.metrics import MetricPlugin, metric
from eval.models import MetricResult, TestCase


def _extract_tool_calls(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull all tool calls from the trace messages."""
    calls: list[dict[str, Any]] = []
    for msg in trace.get("messages", []):
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls", []):
                calls.append(tc)
    return calls


def _extract_tool_names(trace: dict[str, Any]) -> list[str]:
    """Return an ordered list of tool names called."""
    return [tc.get("name", "") for tc in _extract_tool_calls(trace)]


def _extract_fetched_urls(trace: dict[str, Any]) -> set[str]:
    """Return the set of URLs passed to fetch_url."""
    urls: set[str] = set()
    for tc in _extract_tool_calls(trace):
        if tc.get("name") == "fetch_url":
            url = tc.get("args", {}).get("url", "")
            if url:
                urls.add(url)
    return urls


@metric("tool_efficiency")
class ToolEfficiencyMetric(MetricPlugin):
    """Check tool usage efficiency."""

    def score(self, trace: dict[str, Any], test_case: TestCase) -> MetricResult:
        cfg = test_case.metric_config
        tool_names = _extract_tool_names(trace)
        tool_calls_list = _extract_tool_calls(trace)
        total_calls = len(tool_names)
        citations = trace.get("citations", [])
        fetched_urls = _extract_fetched_urls(trace)

        failures: list[str] = []
        details: dict[str, Any] = {
            "total_tool_calls": total_calls,
            "tool_sequence": tool_names,
            "fetched_urls": list(fetched_urls),
        }

        # ── Required tools ─────────────────────────────────────────
        if cfg.required_tools:
            for tool in cfg.required_tools:
                if tool not in tool_names:
                    failures.append(f"required tool not called: {tool}")

        # ── Forbidden tools ────────────────────────────────────────
        if cfg.forbidden_tools:
            for tool in cfg.forbidden_tools:
                if tool in tool_names:
                    failures.append(f"forbidden tool was called: {tool}")

        # ── Max tool calls ─────────────────────────────────────────
        if cfg.max_tool_calls is not None and total_calls > cfg.max_tool_calls:
            failures.append(
                f"too many tool calls: {total_calls} > {cfg.max_tool_calls}"
            )

        # ── Required tool sequence (subsequence check) ─────────────
        if cfg.required_tool_sequence:
            seq = cfg.required_tool_sequence
            idx = 0
            for name in tool_names:
                if idx < len(seq) and name == seq[idx]:
                    idx += 1
            if idx < len(seq):
                failures.append(
                    f"required tool sequence not followed: expected {seq}, "
                    f"got {tool_names}"
                )

        # ── All citations must be fetched ──────────────────────────
        for url in citations:
            if url not in fetched_urls:
                failures.append(f"cited URL not fetched: {url}")

        # ── Score calculation ──────────────────────────────────────
        if failures:
            # Partial score based on how many checks passed
            total_checks = 0
            passed_checks = 0
            if cfg.required_tools:
                total_checks += len(cfg.required_tools)
                passed_checks += sum(
                    1 for t in cfg.required_tools if t in tool_names
                )
            if cfg.max_tool_calls is not None:
                total_checks += 1
                if total_calls <= cfg.max_tool_calls:
                    passed_checks += 1
            if cfg.required_tool_sequence:
                total_checks += 1
            total_checks += len(citations)
            passed_checks += sum(1 for u in citations if u in fetched_urls)

            score = passed_checks / max(total_checks, 1)
        else:
            score = 1.0

        details["failures"] = failures
        return MetricResult(
            metric_name="tool_efficiency",
            passed=len(failures) == 0,
            score=score,
            rationale="; ".join(failures) if failures else "All tool-efficiency checks passed.",
            details=details,
        )
