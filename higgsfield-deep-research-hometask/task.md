# Take-home: Build an Evaluation Framework

## Context

You'll receive access to a private repo, **`deep-research-lite`**: a small, intentionally-imperfect research agent (~400 LOC, Anthropic SDK, 4 tools: `web_search`, `fetch_url`, `extract_quotes`, `finish`). The agent takes one question and returns a cited answer grounded in a local ~35-page corpus.

Your job is to build the framework that evaluates it. Treat the agent as a black box — your framework wraps it, it does not replace it.

Part of the exercise is discovering *how* the agent is imperfect. We won't tell you which bugs are planted. A strong submission finds several of them without being told.

## Time & budget

- **~6–8 hours** of your time. We're not grading raw hours; we're grading what you ship and how you reason about it.
- **~$15 reimbursable** for API spend. Evals burn tokens — use a cheap judge model.
- **Stack:** Python or TypeScript. Anthropic SDK (matching the agent). A CLI and a minimal local HTML viewer. No frontend framework. No DB. No hosted dashboard.

## What to build

A framework that:

1. **Loads a test suite** from a directory of YAML or JSON cases. Each case declares:
   - `input` — the user message sent to the agent
   - `expected_behavior` — a mix of:
     - **Hard assertions** (deterministic checks over the trace): e.g. "tool X was called", "final answer contains substring Y", "tool call count ≤ N", "stopped_reason == finish", "every citation URL appears as a `fetch_url` argument in the trace"
     - **Soft assertions** (LLM-as-judge with a rubric): e.g. "the answer is factually correct", "the agent appropriately declined", "contradicting sources are disclosed"

2. **Runs cases in parallel** with a configurable concurrency cap. Respects provider rate limits. Retries on transient errors (429, 5xx, network). **Never retries on assertion failures.**

3. **Captures full traces per run** — every message, every tool call (inputs + outputs), timings, token counts, cost estimate, errors. Traces persist to disk as JSON. The agent already emits a trace; you may extend the format. Re-scoring a cached trace must work **without re-calling the agent**.

4. **Scores each case** on its declared metrics and produces a run report:
   - Per-case pass / fail with a short failure reason
   - Aggregate: pass rate, total cost, p50/p95 latency, mean tool calls per case
   - **Diff vs previous run**, with regressions clearly flagged

5. **Trace viewer.** A local HTML file (one per run is fine) that shows the message timeline with expandable tool-call I/O. A human should find the failing step in under 30 seconds.

6. **Flakiness as a first-class concept.** A `--repeats N` flag. When N > 1, the report shows "3/5 passed" plus variance per metric, not a hidden average.

## Required metrics

At minimum, each case gets scored on:
- **Correctness** (hard + LLM-judge combined)
- **Tool efficiency** — missing a required tool or making unnecessary calls
- **Cost & latency**
- **Safety / format compliance** — structured output, system-prompt leak, refusal correctness

**Adding a new metric must not require editing the runner or scorer core.** Register metrics via a plugin-style hook — even a naive one is fine.

## Test suite (≥10 cases you write)

Your suite must cover, at minimum:

- **≥2 happy paths** that should pass cleanly.
- **≥1 ambiguous prompt** where the agent should either ask for clarification or disclose ambiguity.
- **≥1 refusal case** where the agent *should* decline (hint: the corpus is not uniformly public-domain information).
- **≥1 case with a required tool sequence** you assert on.
- **≥1 adversarial / prompt-injection case.**
- **≥1 case designed to catch a specific behavioral failure** you hypothesized from reading the agent code and corpus.

We're looking for evidence you thought adversarially about what could go wrong with *this specific agent*.

## LLM-as-judge requirements

- Judge must return **structured output with a rationale**, not a raw number.
- **Rubric per case or per metric**, not a generic prompt. Rubrics live in checked-in files you can show us.
- Judge uses a **cheaper model than the agent under test** (the agent runs on `claude-haiku-4-5`; use something comparable or a different family with strong rubrics).
- **Validate your judge.** Spot-check enough of its verdicts by hand that you can report a defensible agreement rate in the README. If the judge disagrees with you in ways that matter, describe how you iterated on the rubric.
- In the README, acknowledge known judge failure modes you did or did not address: position bias, self-preference, injection-through-agent-output, rubric ambiguity.

## Deliverables

1. **A repo** (GitHub or attached zip) with one-command setup (`make test` / `pytest` / equivalent).
2. **Your test suite** (≥10 cases).
3. **Traces from your own runs**, committed as fixtures so we can re-score without re-running.
4. **README** with:
   - How to run a single case, the full suite, and a diff against a previous run.
   - Your LLM-judge design and how you validated it isn't garbage.
   - A "**Bugs I found in the shipped agent**" section. List what you caught and how your framework surfaced it. Finding bugs is part of the signal.
   - A "**What I'd add next**" section — sampling strategies, statistical significance, golden-set maintenance, drift detection, etc.
5. **3–5 minute Loom**: run the suite, intentionally break the agent with a one-line change (e.g. edit the system prompt), re-run, show the regression surface in the report.

## Ground rules

- Don't modify the agent or its tools. Your framework wraps the agent, it doesn't replace it.
- Don't commit `.env` or API keys. `.env.example` only.
- Don't commit `traces/` of your development runs — do commit a small set of *fixture* traces for reproducibility.
- Don't share the repo or your submission publicly.

## How we'll evaluate

| Area | What good looks like |
|---|---|
| **AI-engineering literacy** | Clear grasp of LLM-judge pitfalls (position bias, self-preference, bad rubrics). Sensible token/cost accounting. Understands that a single run isn't a score. |
| **Backend craft** | Clean separation between runner, scorer, reporter, viewer. Parallelism done right (no thundering herd). Traces are a real data model, not prints. Determinism where possible — seeded, recorded, replayable. |
| **Product judgment** | The reports are actually useful. A human finds the regression in under 30 seconds. The viewer is something you'd want to look at. |
| **Test design** | The cases reveal you thought about what could go wrong with *this agent*, not just what it should do. Cases cover distinct failure modes, not variations of the same theme. |

## Out of scope

Auth, hosted dashboard, DB, CI beyond a single test command, fixing the agent.

## Questions?

Reply to the thread you received this in. If it's a clarifying question about the take-home, we'll answer. If it's a leading question about whether a specific defect exists in the agent, we won't — that's part of the signal.

---

Good luck. We're excited to see what you build.
