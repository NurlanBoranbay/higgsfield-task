"""LLM-as-judge — calls claude-sonnet-4-6 for soft evaluations.

The judge is used by metric plugins (correctness, safety) to produce
structured verdicts.  Since there no other models provided by anthropic that are cheaper than haiku 4-5
I used claude-sonnet-4-6 as a judge. Since there is a research proving that if we use the same model for eval it tends to rate it higher than it should (**self-preference bias**).  Though, I also included results of claude-haiku-4-5 run for comparison in the trace.

Rubrics are loaded from the ``rubrics/`` directory and injected into
the system prompt so they are version-controlled and auditable.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from eval.models import JudgeVerdict

JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "claude-sonnet-4-6")
RUBRICS_DIR = Path(__file__).parent.parent / "rubrics"


def _load_rubric(name: str) -> str:
    """Load a rubric markdown file by name (without extension)."""
    path = RUBRICS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Rubric not found: {path}")
    return path.read_text()


def _parse_verdict(raw: str) -> JudgeVerdict:
    """Best-effort parse of the judge's JSON output."""
    raw = raw.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    try:
        data = json.loads(raw)
        return JudgeVerdict(
            passed=bool(data.get("passed", False)),
            score=float(data.get("score", 0.0)),
            rationale=str(data.get("rationale", "No rationale provided")),
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        # If the judge produces unparseable output, fail conservatively
        return JudgeVerdict(
            passed=False,
            score=0.0,
            rationale=f"Judge output could not be parsed: {raw[:300]}",
        )


def judge(
    rubric_name: str,
    question: str,
    answer: str,
    citations: list[str],
    trace_summary: str,
    expected: str = "",
    corpus_context: str = "",
    rubric_override: str = "",
) -> JudgeVerdict:
    """Run the LLM judge against a rubric and return a structured verdict.

    Parameters
    ----------
    rubric_name:
        Name of the rubric file in ``rubrics/`` (e.g. "correctness").
    question:
        The user question sent to the agent.
    answer:
        The agent's final answer.
    citations:
        URLs cited by the agent.
    trace_summary:
        A human-readable summary of the tool-call sequence.
    expected:
        Human-written description of what a correct answer looks like.
    corpus_context:
        Relevant corpus text for the judge to compare against.
    rubric_override:
        Optional per-case rubric addition appended to the base rubric.
    """
    rubric = _load_rubric(rubric_name)
    if rubric_override:
        rubric += f"\n\n## Per-Case Override\n{rubric_override}"

    user_message = f"""## Question
{question}

## Agent's Answer
{answer}

## Citations
{json.dumps(citations)}

## Expected Answer Summary
{expected or "Not specified — use your judgment based on corpus context."}

## Corpus Context
{corpus_context or "Not provided."}

## Trace Summary
{trace_summary}

---

Score this answer according to the rubric. Return ONLY a JSON object with "passed", "score", and "rationale" fields."""

    client = Anthropic()
    resp = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=512,
        temperature=0.0,
        system=rubric,
        messages=[{"role": "user", "content": user_message}],
    )
    raw = "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    )
    return _parse_verdict(raw)


def build_trace_summary(trace: dict[str, Any]) -> str:
    """Build a concise human-readable summary of the agent's tool calls."""
    lines: list[str] = []
    messages = trace.get("messages", [])
    step = 0
    for msg in messages:
        role = msg.get("role", "")
        if role == "assistant":
            text = msg.get("text", "")
            tool_calls = msg.get("tool_calls", [])
            if text:
                lines.append(f"  [{step}] Assistant thought: {text[:300]}")
            for tc in tool_calls:
                name = tc.get("name", "?")
                args = tc.get("args", {})
                args_short = json.dumps(args, default=str)[:400]
                lines.append(f"  [{step}] Called {name}({args_short})")
            step += 1
        elif role == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                lines.append(f"  [{step}] User: {content[:300]}")
            else:
                lines.append(f"  [{step}] User: <complex block>")
        elif role == "tool":
            name = msg.get("name", "?")
            content = msg.get("content", "")
            content_str = json.dumps(content, default=str) if not isinstance(content, str) else content
            lines.append(f"        → {name} returned: {content_str[:500]}")
            
    stopped_reason = trace.get("stopped_reason")
    error = trace.get("error")
    if error:
        lines.append(f"\n[Agent stopped with error: {error}]")
    elif stopped_reason:
        lines.append(f"\n[Agent stopped with reason: {stopped_reason}]")
        
    return "\n".join(lines)
