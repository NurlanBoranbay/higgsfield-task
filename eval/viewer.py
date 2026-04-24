"""HTML trace viewer generator.

Produces a self-contained HTML file (inline CSS + JS) for a single
evaluation run.  Design priorities:

1. **Failure rationale first** — red box at top for failed cases.
2. **Color-coded tool badges** — instant visual scanning.
3. **Expandable tool I/O** — collapsed by default, auto-expanded on error.
4. **Find the failing step in under 30 seconds.**
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from eval.models import EvalRun


def _tool_badge(name: str) -> str:
    """Return an HTML badge for a tool name."""
    badges = {
        "web_search": ("🔍 Searching", "#3b82f6", "#1e3a5f"),
        "fetch_url": ("📄 Fetching", "#8b5cf6", "#3b1f6e"),
        "extract_quotes": ("💬 Extracting", "#f59e0b", "#5c3d0a"),
        "finish": ("✅ Done", "#22c55e", "#0a3d1a"),
    }
    label, bg, border = badges.get(name, (f"🔧 {name}", "#6b7280", "#374151"))
    return (
        f'<span class="tool-badge" style="background:{bg};border-color:{border}">'
        f"{label}</span>"
    )


def _escape(text: Any) -> str:
    """Escape text for safe HTML embedding."""
    return html.escape(str(text)) if text else ""


def _format_json(data: Any, max_len: int = 2000) -> str:
    """Format data as pretty JSON, truncated if needed."""
    try:
        formatted = json.dumps(data, indent=2, default=str)
        if len(formatted) > max_len:
            formatted = formatted[:max_len] + "\n... (truncated)"
        return _escape(formatted)
    except (TypeError, ValueError):
        return _escape(str(data)[:max_len])


def _render_case(case_result: dict[str, Any], idx: int) -> str:
    """Render a single case result as HTML."""
    test_id = case_result.get("test_case_id", f"case-{idx}")
    passed = case_result.get("passed", False)
    trace = case_result.get("trace", {})
    metrics = case_result.get("metric_results", [])
    failures = case_result.get("failure_reasons", [])
    question = trace.get("question", "N/A")
    answer = trace.get("final_answer", "N/A") or "N/A"
    messages = trace.get("messages", [])

    status_class = "pass" if passed else "fail"
    status_text = "PASS ✅" if passed else "FAIL ❌"

    # ── Failure banner ─────────────────────────────────────────
    failure_html = ""
    if not passed:
        reasons = "<br>".join(_escape(r) for r in failures)
        failure_html = f"""
        <div class="failure-banner">
            <div class="failure-title">❌ Failure Rationale</div>
            <div class="failure-body">{reasons}</div>
        </div>"""

    # ── Metric scorecard ───────────────────────────────────────
    metric_cards = ""
    for m in metrics:
        m_pass = m.get("passed", False)
        m_name = m.get("metric_name", "?")
        m_score = m.get("score", 0)
        m_class = "metric-pass" if m_pass else "metric-fail"
        metric_cards += f"""
            <div class="metric-card {m_class}">
                <div class="metric-name">{_escape(m_name)}</div>
                <div class="metric-score">{m_score:.2f}</div>
            </div>"""

    # ── Message timeline ───────────────────────────────────────
    timeline_html = ""
    for msg in messages:
        role = msg.get("role", "")

        if role == "system":
            continue

        if role == "user":
            timeline_html += f"""
            <div class="timeline-item user-msg">
                <div class="timeline-role">👤 User</div>
                <div class="timeline-content">{_escape(msg.get('content', ''))}</div>
            </div>"""

        elif role == "assistant":
            text = msg.get("text", "")
            tool_calls = msg.get("tool_calls", [])
            latency = msg.get("latency_ms", 0)

            text_html = f'<div class="assistant-thought">{_escape(text)}</div>' if text else ""
            tools_html = ""
            for tc in tool_calls:
                tc_name = tc.get("name", "?")
                tc_args = tc.get("args", {})
                badge = _tool_badge(tc_name)
                args_formatted = _format_json(tc_args)
                tools_html += f"""
                <div class="tool-call">
                    <div class="tool-call-header" onclick="this.parentElement.classList.toggle('expanded')">
                        {badge}
                        <span class="tool-latency">{latency}ms</span>
                        <span class="expand-icon">▶</span>
                    </div>
                    <div class="tool-call-body">
                        <pre class="tool-args">{args_formatted}</pre>
                    </div>
                </div>"""

            timeline_html += f"""
            <div class="timeline-item assistant-msg">
                <div class="timeline-role">🤖 Assistant</div>
                {text_html}
                {tools_html}
            </div>"""

        elif role == "tool":
            tool_name = msg.get("name", "?")
            content = msg.get("content", "")
            latency = msg.get("latency_ms", 0)
            is_error = isinstance(content, dict) and "error" in content
            error_class = "tool-error" if is_error else ""
            expanded = "expanded" if is_error else ""

            content_formatted = _format_json(content)
            badge = _tool_badge(tool_name)

            timeline_html += f"""
            <div class="timeline-item tool-result {error_class} {expanded}">
                <div class="tool-result-header" onclick="this.parentElement.classList.toggle('expanded')">
                    {badge}
                    <span class="tool-result-label">→ result</span>
                    <span class="tool-latency">{latency}ms</span>
                    <span class="expand-icon">▶</span>
                </div>
                <div class="tool-result-body">
                    <pre class="tool-output">{content_formatted}</pre>
                </div>
            </div>"""

    # ── Final answer ───────────────────────────────────────────
    citations = trace.get("citations", [])
    citations_html = "".join(
        f'<div class="citation">[{i+1}] {_escape(c)}</div>'
        for i, c in enumerate(citations)
    )

    cost = trace.get("cost_usd", 0)
    latency_total = trace.get("wall_time_ms", 0)
    tokens = trace.get("total_tokens", {})

    return f"""
    <div class="case-card {status_class}" id="case-{idx}">
        <div class="case-header" onclick="this.parentElement.classList.toggle('collapsed')">
            <span class="case-status">{status_text}</span>
            <span class="case-id">{_escape(test_id)}</span>
            <span class="case-stats">${cost:.4f} · {latency_total}ms</span>
            <span class="expand-icon">▼</span>
        </div>
        <div class="case-body">
            {failure_html}
            <div class="metric-grid">{metric_cards}</div>
            <div class="case-section">
                <div class="section-title">Question</div>
                <div class="question-text">{_escape(question)}</div>
            </div>
            <div class="case-section">
                <div class="section-title">Timeline</div>
                <div class="timeline">{timeline_html}</div>
            </div>
            <div class="case-section">
                <div class="section-title">Final Answer</div>
                <div class="answer-text">{_escape(answer)}</div>
                {f'<div class="citations">{citations_html}</div>' if citations else ''}
            </div>
            <div class="case-meta">
                Tokens: {tokens.get('input', 0)} in / {tokens.get('output', 0)} out ·
                Cost: ${cost:.4f} · Wall: {latency_total}ms ·
                Stopped: {_escape(trace.get('stopped_reason', '?'))}
            </div>
        </div>
    </div>"""


def _format_timestamp(ts: str) -> str:
    """Format ISO timestamp to human-readable form."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y at %H:%M UTC")
    except (ValueError, AttributeError):
        return ts


def generate_viewer(report: EvalRun, output_path: Path) -> Path:
    """Generate a self-contained HTML trace viewer for a run."""
    agg = report.aggregate
    formatted_ts = _format_timestamp(report.timestamp)

    # ── Render all cases ───────────────────────────────────────
    cases_html = ""
    for idx, cr in enumerate(report.case_results):
        cases_html += _render_case(cr.model_dump(), idx)

    # ── Aggregate stats bar ────────────────────────────────────
    agg_html = ""
    if agg:
        pass_pct = f"{agg.pass_rate:.0%}"
        agg_html = f"""
        <div class="aggregate-bar">
            <div class="agg-item">
                <span class="agg-label">Pass Rate</span>
                <span class="agg-value">{agg.passed_cases}/{agg.total_cases} ({pass_pct})</span>
            </div>
            <div class="agg-item">
                <span class="agg-label">Cost</span>
                <span class="agg-value">${agg.total_cost_usd:.4f}</span>
            </div>
            <div class="agg-item">
                <span class="agg-label">p50 Latency</span>
                <span class="agg-value">{agg.p50_latency_ms:.0f}ms</span>
            </div>
            <div class="agg-item">
                <span class="agg-label">p95 Latency</span>
                <span class="agg-value">{agg.p95_latency_ms:.0f}ms</span>
            </div>
            <div class="agg-item">
                <span class="agg-label">Avg Tools</span>
                <span class="agg-value">{agg.mean_tool_calls:.1f}/case</span>
            </div>
        </div>"""

    # ── Diff section (regressions + improvements) ──────────────
    diff_html = ""
    if report.diffs:
        regressions = [d for d in report.diffs if d.is_regression]
        improvements = [
            d for d in report.diffs
            if not d.is_regression and d.current_passed and not d.previous_passed
        ]
        if regressions:
            diff_items = ""
            for d in regressions:
                metric_deltas = ""
                for name, md in d.metric_diffs.items():
                    if md.get("prev_passed") and not md.get("curr_passed"):
                        metric_deltas += (
                            f'<div class="regression-detail">'
                            f'└─ {_escape(name)}: {md["prev_score"]:.2f} → {md["curr_score"]:.2f}'
                            f'</div>'
                        )
                diff_items += (
                    f'<div class="regression-item">'
                    f'⚠️ {_escape(d.test_case_id)}: PASS → FAIL'
                    f'{metric_deltas}</div>'
                )
            diff_html += f"""
            <div class="diff-section diff-regression">
                <div class="diff-title">⚠️ Regressions ({len(regressions)})</div>
                {diff_items}
            </div>"""
        if improvements:
            imp_items = ""
            for d in improvements:
                imp_items += f'<div class="improvement-item">✅ {_escape(d.test_case_id)}: FAIL → PASS</div>'
            diff_html += f"""
            <div class="diff-section diff-improvement">
                <div class="diff-title diff-title-pass">🎉 Improvements ({len(improvements)})</div>
                {imp_items}
            </div>"""

    # ── Repeat results section ─────────────────────────────────
    import statistics
    repeat_html = ""
    if report.repeat_results:
        repeat_rows = ""
        for rr in report.repeat_results:
            pass_pct_r = f"{rr.passed_runs}/{rr.total_runs}"
            metric_details = ""
            if rr.total_runs > 1:
                metrics_dict: dict[str, list[float]] = {}
                for cr in rr.results:
                    for m in cr.metric_results:
                        metrics_dict.setdefault(m.metric_name, []).append(m.score)
                for m_name, scores in metrics_dict.items():
                    if len(scores) > 1:
                        variance = statistics.pvariance(scores)
                        mean_val = statistics.mean(scores)
                        metric_details += (
                            f'<div class="repeat-metric">'
                            f'└─ {_escape(m_name)}: mean={mean_val:.2f}, var={variance:.4f}'
                            f'</div>'
                        )
            status_cls = "pass" if rr.passed_runs == rr.total_runs else (
                "fail" if rr.passed_runs == 0 else "flaky"
            )
            repeat_rows += (
                f'<div class="repeat-row {status_cls}">'
                f'<span class="repeat-id">{_escape(rr.test_case_id)}</span>'
                f'<span class="repeat-rate">{pass_pct_r}</span>'
                f'{metric_details}</div>'
            )
        repeat_html = f"""
        <div class="repeat-section collapsed" id="repeatSection">
            <div class="repeat-header" onclick="toggleRepeat()">
                <span class="expand-icon">▶</span>
                <span class="section-title">🔄 Flakiness Results (--repeats {report.repeats})</span>
            </div>
            <div class="repeat-body">
                {repeat_rows}
            </div>
        </div>"""

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Eval Run: {report.run_id}</title>
<style>
:root {{
    --bg-primary: #0f1117;
    --bg-secondary: #1a1d27;
    --bg-tertiary: #252830;
    --text-primary: #e4e4e7;
    --text-secondary: #a1a1aa;
    --text-muted: #71717a;
    --border: #2e3039;
    --pass: #22c55e;
    --pass-bg: rgba(34, 197, 94, 0.08);
    --fail: #ef4444;
    --fail-bg: rgba(239, 68, 68, 0.08);
    --accent: #3b82f6;
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
    padding: 2rem;
    max-width: 1100px;
    margin: 0 auto;
}}

h1 {{
    font-size: 1.5rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: var(--text-primary);
}}

.subtitle {{
    color: var(--text-muted);
    font-size: 0.85rem;
    margin-bottom: 1.5rem;
}}

/* Aggregate bar */
.aggregate-bar {{
    display: flex;
    gap: 1rem;
    padding: 1rem 1.25rem;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
}}
.agg-item {{
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    min-width: 120px;
}}
.agg-label {{
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
}}
.agg-value {{
    font-size: 1.05rem;
    font-weight: 600;
    color: var(--text-primary);
}}

/* Diff / regression */
.diff-section {{
    padding: 1rem 1.25rem;
    border-radius: 10px;
    margin-bottom: 1rem;
}}
.diff-regression {{
    background: var(--fail-bg);
    border: 1px solid rgba(239, 68, 68, 0.25);
}}
.diff-improvement {{
    background: var(--pass-bg);
    border: 1px solid rgba(34, 197, 94, 0.25);
}}
.diff-title {{
    font-weight: 600;
    color: var(--fail);
    margin-bottom: 0.5rem;
}}
.diff-title-pass {{
    color: var(--pass);
}}
.regression-item, .improvement-item {{
    color: var(--text-primary);
    padding: 0.25rem 0;
    font-size: 0.9rem;
}}
.regression-detail {{
    color: var(--text-muted);
    font-size: 0.8rem;
    padding-left: 1.5rem;
    font-family: monospace;
}}

/* Repeat / flakiness */
.repeat-section {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 1.5rem;
    overflow: hidden;
}}
.repeat-header {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.85rem 1.25rem;
    cursor: pointer;
    user-select: none;
}}
.repeat-header:hover {{ background: var(--bg-tertiary); }}
.repeat-header .expand-icon {{
    color: var(--text-muted);
    font-size: 0.7rem;
    transition: transform 0.2s;
}}
.repeat-section:not(.collapsed) .repeat-header .expand-icon {{ transform: rotate(90deg); }}
.repeat-body {{
    padding: 0 1.25rem 1rem;
}}
.repeat-section.collapsed .repeat-body {{ display: none; }}
.repeat-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    padding: 0.4rem 0;
    border-bottom: 1px solid var(--border);
    align-items: center;
}}
.repeat-row:last-child {{ border-bottom: none; }}
.repeat-row.flaky {{ color: #f59e0b; }}
.repeat-id {{
    font-weight: 500;
    min-width: 220px;
    font-size: 0.85rem;
}}
.repeat-rate {{
    font-weight: 600;
    min-width: 60px;
    font-size: 0.85rem;
}}
.repeat-metric {{
    width: 100%;
    color: var(--text-muted);
    font-size: 0.78rem;
    padding-left: 1.5rem;
    font-family: monospace;
}}

/* Search box */
.search-box {{
    width: 100%;
    padding: 0.5rem 0.75rem;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 0.85rem;
    font-family: inherit;
    margin-bottom: 0.75rem;
    outline: none;
    transition: border-color 0.15s;
}}
.search-box:focus {{
    border-color: var(--accent);
}}
.search-box::placeholder {{
    color: var(--text-muted);
}}

/* Case card */
.case-card {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 0.75rem;
    overflow: hidden;
    transition: border-color 0.2s;
}}
.case-card.pass {{ border-left: 3px solid var(--pass); }}
.case-card.fail {{ border-left: 3px solid var(--fail); }}
.case-card.collapsed .case-body {{ display: none; }}

.case-header {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.85rem 1.25rem;
    cursor: pointer;
    user-select: none;
}}
.case-header:hover {{ background: var(--bg-tertiary); }}
.case-status {{
    font-weight: 600;
    font-size: 0.85rem;
    min-width: 70px;
}}
.pass .case-status {{ color: var(--pass); }}
.fail .case-status {{ color: var(--fail); }}
.case-id {{
    font-weight: 500;
    flex-grow: 1;
    font-size: 0.9rem;
}}
.case-stats {{
    color: var(--text-muted);
    font-size: 0.8rem;
    font-family: 'SF Mono', 'Fira Code', monospace;
}}
.case-header .expand-icon {{
    color: var(--text-muted);
    font-size: 0.7rem;
    transition: transform 0.2s;
}}
.case-card.collapsed .case-header .expand-icon {{ transform: rotate(-90deg); }}

.case-body {{
    padding: 0 1.25rem 1.25rem;
}}

/* Failure banner */
.failure-banner {{
    background: var(--fail-bg);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 8px;
    padding: 1rem;
    margin-bottom: 1rem;
}}
.failure-title {{
    font-weight: 600;
    color: var(--fail);
    margin-bottom: 0.4rem;
    font-size: 0.9rem;
}}
.failure-body {{
    color: var(--text-primary);
    font-size: 0.85rem;
    line-height: 1.5;
}}

/* Metric grid */
.metric-grid {{
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
}}
.metric-card {{
    padding: 0.5rem 0.75rem;
    border-radius: 8px;
    min-width: 100px;
    text-align: center;
}}
.metric-pass {{
    background: var(--pass-bg);
    border: 1px solid rgba(34, 197, 94, 0.2);
}}
.metric-fail {{
    background: var(--fail-bg);
    border: 1px solid rgba(239, 68, 68, 0.2);
}}
.metric-name {{
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted);
    margin-bottom: 0.15rem;
}}
.metric-score {{
    font-size: 1.1rem;
    font-weight: 700;
}}
.metric-pass .metric-score {{ color: var(--pass); }}
.metric-fail .metric-score {{ color: var(--fail); }}

/* Sections */
.case-section {{
    margin-bottom: 1rem;
}}
.section-title {{
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 0.4rem;
    font-weight: 600;
}}
.question-text, .answer-text {{
    background: var(--bg-tertiary);
    padding: 0.75rem 1rem;
    border-radius: 8px;
    font-size: 0.9rem;
}}

/* Citations */
.citations {{
    margin-top: 0.4rem;
}}
.citation {{
    font-size: 0.8rem;
    color: var(--accent);
    padding: 0.1rem 0;
    font-family: 'SF Mono', 'Fira Code', monospace;
}}

/* Timeline */
.timeline {{
    border-left: 2px solid var(--border);
    margin-left: 0.5rem;
    padding-left: 1rem;
}}
.timeline-item {{
    margin-bottom: 0.6rem;
    padding: 0.6rem 0.85rem;
    border-radius: 8px;
    font-size: 0.85rem;
}}
.user-msg {{ background: rgba(59, 130, 246, 0.06); }}
.assistant-msg {{ background: var(--bg-tertiary); }}
.tool-result {{ background: var(--bg-primary); }}
.tool-error {{ background: var(--fail-bg) !important; }}

.timeline-role {{
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 0.3rem;
}}
.assistant-thought {{
    color: var(--text-secondary);
    font-style: italic;
    margin-bottom: 0.4rem;
    font-size: 0.85rem;
}}

/* Tool call / result */
.tool-call, .tool-result {{
    margin-top: 0.3rem;
}}
.tool-call-header, .tool-result-header {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
    user-select: none;
    padding: 0.3rem 0;
}}
.tool-call-body, .tool-result-body {{
    display: none;
    margin-top: 0.3rem;
}}
.tool-call.expanded .tool-call-body,
.tool-result.expanded .tool-result-body,
.timeline-item.expanded .tool-result-body {{
    display: block;
}}
.tool-call.expanded .expand-icon,
.tool-result.expanded .expand-icon,
.timeline-item.expanded .expand-icon {{
    transform: rotate(90deg);
}}
.expand-icon {{
    color: var(--text-muted);
    font-size: 0.65rem;
    transition: transform 0.15s;
    margin-left: auto;
}}

.tool-badge {{
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.2rem 0.6rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    border: 1px solid;
    color: white;
}}
.tool-latency {{
    font-size: 0.72rem;
    color: var(--text-muted);
    font-family: monospace;
}}
.tool-result-label {{
    font-size: 0.75rem;
    color: var(--text-secondary);
}}

.tool-args, .tool-output {{
    background: var(--bg-primary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.6rem;
    font-size: 0.78rem;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--text-secondary);
    max-height: 300px;
    overflow-y: auto;
}}

/* Case meta */
.case-meta {{
    font-size: 0.75rem;
    color: var(--text-muted);
    padding-top: 0.5rem;
    border-top: 1px solid var(--border);
    font-family: monospace;
}}

/* Filter buttons */
.filters {{
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
}}
.filter-btn {{
    padding: 0.4rem 0.8rem;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-secondary);
    color: var(--text-secondary);
    cursor: pointer;
    font-size: 0.8rem;
    font-family: inherit;
    transition: all 0.15s;
}}
.filter-btn:hover {{ background: var(--bg-tertiary); }}
.filter-btn.active {{
    background: var(--accent);
    color: white;
    border-color: var(--accent);
}}
</style>
</head>
<body>
<h1>🔬 Eval Run: {report.run_id}</h1>
<div class="subtitle">Model: {report.model} · {formatted_ts}</div>

{agg_html}
{diff_html}
{repeat_html}

<input type="text" class="search-box" id="searchBox"
       placeholder="🔍 Search cases by ID or question..."
       oninput="searchCases(this.value)">

<div class="filters">
    <button class="filter-btn active" onclick="filterCases('all')">All</button>
    <button class="filter-btn" onclick="filterCases('fail')">Failed</button>
    <button class="filter-btn" onclick="filterCases('pass')">Passed</button>
</div>

<div id="cases">
{cases_html}
</div>

<script>
function filterCases(type) {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
    const query = document.getElementById('searchBox').value.toLowerCase();
    document.querySelectorAll('.case-card').forEach(card => {{
        const text = card.textContent.toLowerCase();
        const matchesSearch = !query || text.includes(query);
        const matchesFilter = type === 'all' ||
            (type === 'fail' && card.classList.contains('fail')) ||
            (type === 'pass' && card.classList.contains('pass'));
        card.style.display = (matchesSearch && matchesFilter) ? '' : 'none';
    }});
}}

function searchCases(query) {{
    query = query.toLowerCase();
    const activeFilter = document.querySelector('.filter-btn.active');
    const type = activeFilter ? activeFilter.textContent.toLowerCase().trim() : 'all';
    const filterMap = {{ 'all': 'all', 'failed': 'fail', 'passed': 'pass' }};
    document.querySelectorAll('.case-card').forEach(card => {{
        const text = card.textContent.toLowerCase();
        const matchesSearch = !query || text.includes(query);
        const ft = filterMap[type] || 'all';
        const matchesFilter = ft === 'all' ||
            (ft === 'fail' && card.classList.contains('fail')) ||
            (ft === 'pass' && card.classList.contains('pass'));
        card.style.display = (matchesSearch && matchesFilter) ? '' : 'none';
    }});
}}

function toggleRepeat() {{
    const section = document.getElementById('repeatSection');
    if (section) section.classList.toggle('collapsed');
}}
</script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_html)
    return output_path
