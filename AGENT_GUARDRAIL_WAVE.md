# Trending graph walkthrough — the "agent guardrail" wave (2026-07-27)

*A snapshot finding from reading the correlation graph (`/graph?trending=true`) entity by entity.
Not a design doc — a dated observation. If the underlying data changes materially, this file goes
stale; re-derive rather than trust it blindly.*

## Reading "trending" correctly first

The system surfaces two different signals under that word, and they should not be conflated:

- **`gate_decisions` (pass)** — the real, curated signal. Weekly budget of ≤5 briefs, scored by the
  M×R×N significance formula. If something passed the gate, it earned the attention.
- **`momentum_states` (breakout / accelerating)** — a raw daily signal, much noisier. As of this
  writing, 411 entities carry one of these two states, but most of that is a known artifact
  (HANDOFF.md §19.3): the entire hand-seeded catalog of well-known tools (LangChain, vLLM, Qdrant,
  etc.) reads as "accelerating" purely because tracking on them only just started (cold start), not
  because they're actually surging. Do not read raw momentum state as ground truth on its own —
  cross-check against the gate.

## What actually passed the gate this week (2026-07-20)

Five entities passed, plus one from an earlier week still worth noting. All six cluster in the same
cohort (`project`, `agent-framework`/`rag-framework`, 0–30 days old) — and, more interesting than
the momentum numbers, they all tell the *same story*:

| Entity | What it is | Category |
|---|---|---|
| `uipath/coder_eval` | Eval framework for CLI/skill-building coding agents (sandboxing, reproducibility) | agent-framework |
| `termaxa/termaxa` | "Cooperative gate" — controls what a coding agent is allowed to execute via shell | agent-framework |
| `hyperlogue/r3` | Local code-review tool, built for both humans and AI agents | agent-framework |
| `video-db/open-record-replay` | Records agent desktop workflows and turns them into reusable "skills" | agent-framework |
| `pierreolivierbonin/verbatimeter` | Measures whether AI-generated text is actually grounded in its source (LCS method) | rag-framework |
| `skyphusion-labs/postern` *(gated earlier, now dormant)* | Self-hostable email system built for AI agents (SMTP/IMAP/webmail/MCP over Cloudflare) | rag-framework |

## The connecting thread

None of these are new models. They're all small, independent tools whose sole job is to **not
trust an AI agent's output or actions at face value** — code review, shell-command gating, skill
verification, groundedness checking. As coding/agent tooling gets more capable and more autonomous,
a distinct micro-category of verification/guardrail tooling is forming around it in parallel.

## The connections themselves

No deterministic graph edges (`built_by` / `cited` / `depends_on`) link any of the six to each
other or to anything else — expected, since they're all brand-new, unrelated repos with no shared
lineage yet. What does connect them is the LLM-reasoned semantic layer, and each one points to a
*different* neighboring project in the same space, not to each other:

- `hyperlogue/r3` → semantically similar to `elliot-rosen/adversarial-review`
- `termaxa/termaxa` → semantically similar to `ourbando/gatewarden`
- `uipath/coder_eval` → semantically similar to `ozperium/agentspec`
- `pierreolivierbonin/verbatimeter` → semantically similar to `swp0569/rag-llm-consistency-gate`

Every one of those pairings is the same relationship type ("another agent-distrust tool") — six
independent data points converging on one shape isn't noise.

## Where to look

`http://localhost:3000/graph?trending=true` (now the default view — see below) renders this
directly: 🔥-marked seed nodes for the gate/momentum signal, deterministic edges in teal, reasoned
edges in purple. Click any node for its card summary and a link to `/entity/{id}`.

## Dashboard follow-up shipped alongside this note

`/graph` now defaults to trending-only (`?trending=false` to see the full long-tail snapshot) and
has a search box (top-left) that filters the visible graph down to matching entities plus their
direct neighbors, with autocomplete and camera-focus on selection — see `GraphView.tsx`.
