"""Grounding metric — verifies extracted quotes are verbatim.

Registered as ``@metric("grounding")``.  Catches the planted defect in
``extract_quotes`` where the small LLM may paraphrase or hallucinate
quotes.  For each ``extract_quotes`` tool call in the trace, we compare
the returned quotes against the text that was passed into the function
and flag any that do not appear verbatim.
"""

from __future__ import annotations

import json
from typing import Any

from eval.metrics import MetricPlugin, metric
from eval.models import MetricResult, TestCase


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace for fuzzy matching."""
    return " ".join(text.lower().split())


def _find_extract_pairs(trace: dict[str, Any]) -> list[tuple[dict, Any]]:
    """Find (extract_quotes call args, result) pairs from the trace.

    Walks messages looking for an assistant tool_call named
    ``extract_quotes`` immediately followed by its tool result.
    """
    messages = trace.get("messages", [])
    pairs: list[tuple[dict, Any]] = []

    # Build a map of tool_use_id → args for extract_quotes calls
    pending: dict[str, dict] = {}
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls", []):
                if tc.get("name") == "extract_quotes":
                    tool_id = tc.get("id", "")
                    pending[tool_id] = tc.get("args", {})

        elif msg.get("role") == "tool" and msg.get("name") == "extract_quotes":
            tool_id = msg.get("tool_use_id", "")
            if tool_id in pending:
                pairs.append((pending.pop(tool_id), msg.get("content")))

    return pairs


@metric("grounding")
class GroundingMetric(MetricPlugin):
    """Verify that extract_quotes outputs are verbatim from their source text."""

    def score(self, trace: dict[str, Any], test_case: TestCase) -> MetricResult:
        pairs = _find_extract_pairs(trace)

        # If extract_quotes was never called, this metric is not applicable
        if not pairs:
            return MetricResult(
                metric_name="grounding",
                passed=True,
                score=1.0,
                rationale="extract_quotes was not called; grounding check N/A.",
                details={"extract_calls": 0},
            )

        total_quotes = 0
        verbatim_quotes = 0
        hallucinated: list[dict[str, str]] = []

        for args, result in pairs:
            source_text = _normalize(args.get("text", ""))

            # Result may be a list of strings or a JSON-encoded list
            quotes: list[str] = []
            if isinstance(result, list):
                quotes = [str(q) for q in result]
            elif isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, list):
                        quotes = [str(q) for q in parsed]
                except (json.JSONDecodeError, ValueError):
                    quotes = [result]

            for quote in quotes:
                total_quotes += 1
                normalized_quote = _normalize(quote)
                if normalized_quote in source_text:
                    verbatim_quotes += 1
                else:
                    # Check if at least 80% of words appear in the source
                    # to distinguish paraphrasing from pure hallucination
                    quote_words = set(normalized_quote.split())
                    source_words = set(source_text.split())
                    overlap = len(quote_words & source_words) / max(len(quote_words), 1)
                    hallucinated.append({
                        "quote": quote[:200],
                        "word_overlap": round(overlap, 2),
                        "is_paraphrase": overlap > 0.6,
                    })

        score = verbatim_quotes / max(total_quotes, 1)
        passed = len(hallucinated) == 0

        details = {
            "extract_calls": len(pairs),
            "total_quotes": total_quotes,
            "verbatim_quotes": verbatim_quotes,
            "hallucinated": hallucinated,
        }

        if hallucinated:
            rationale = (
                f"{len(hallucinated)}/{total_quotes} quotes are not verbatim. "
                f"The extract_quotes tool may be paraphrasing or hallucinating."
            )
        else:
            rationale = f"All {total_quotes} extracted quotes are verbatim from source text."

        return MetricResult(
            metric_name="grounding",
            passed=passed,
            score=round(score, 2),
            rationale=rationale,
            details=details,
        )
