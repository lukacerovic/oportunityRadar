# Resume: community-discussion AI summarizer

**Last updated: 2026-07-26.** Supersedes the earlier version of this file, which described the
ollama/qwen verdict loop. That approach is being replaced — do not follow those instructions.

Goal: for every entity where we collected community discussion, produce **one structured summary of
what the community actually said** — sentiment, what people like, what they complain about, key
themes, representative quotes. This is a summary of the *discussion*, not of the project.

> **Not to be confused with `comprehension_cards`.** That table holds the LLM summary of the
> *project itself* (976 rows, mostly qwen). The discussion verdict lives in
> `entity_community_research` with `source='summary'` and shares no code path with it —
> `_load_sources()` (`community/verdict.py:312`) reads only the `github`/`hf`/`hn` rows'
> `threads[].comments`. The name `source='summary'` means "cross-source synthesis of the
> discussion", which is confusing; it does not mean "project summary".

---

## 1. Where we are

**Collection: done** for the active momentum tier. Entities with discussion actually found:

| Source | Researched | Found | Hit rate |
|---|---|---|---|
| GitHub (issues + discussions) | 6,008 | 954 | 15.9% |
| Hacker News | 1,110 | 299 | 26.9% |
| Hugging Face | 110 | 53 | 48.2% |
| **Unique entities** | — | **1,123** | — |

**Verdicts: 107 done (all qwen2.5:3b, low quality — to be replaced), ~1,016 pending.**

Why the qwen verdicts are being redone: 65 of 107 came back `positive` with **55 of those having
zero concerns**, 34 were `insufficient_data` with ~80-char summaries, and only 1 was `mixed`. On
the Echo entity it filed the sarcastic *"Wow. What an amazing vector for snooping."* under
`positive_signals`.

## 2. Decisions made

- **Model: Claude Haiku 4.5** (`claude-haiku-4-5`) — now reached via the `claude` CLI rather than
  the API (§4, §9), but the same model and prompt. Chosen after comparing
  tiers: the whole backlog is ~$4 on Haiku vs ~$7 on Sonnet 5 vs ~$18 on Opus 5, so cost was not
  the deciding factor. The task is faithful summarization of supplied comments — not prediction or
  inference — which is well within Haiku's range. **The prompt matters more than the model tier.**
- **A bigger local model is not a substitute — tested, rejected.** `qwen2.5:7b-instruct` was run
  head-to-head against Haiku on the same entities with the *new* prompt (so this is not a
  prompt-quality confound). On `Continue` — an entity whose threads are full of crash reports —
  qwen returned `mixed` and populated `concerns` with pasted user *questions* ("Any plans for
  supporting Jetbrains IDEs?"), which are not complaints; Haiku returned `mostly_negative (38)`
  and surfaced "JetBrains sidebar freezes multiple times daily… users switch to VSCode just to use
  Continue". On `rust-lang/rust`, qwen summarized whatever threads were present (GitHub's
  comment-hiding feature, branch renaming) while Haiku found the actual async-complexity debate.
  Same failure mode as the 3b: it paraphrases the transcript instead of judging it. **$0 is not
  worth it here.**
- **Scope: summarize only.** No adoption prediction, no trajectory inference. If a commenter says
  they run it in production, that is a fact in the comments and gets included; anything not
  traceable to a comment does not.
- **Wire shape unchanged** (`list[str]` for the four list fields), so `api/models.py:111`,
  `dashboard/lib/types.ts:137` and `CommunityVerdict.tsx` needed no changes.

## 3. Code changed this session

| File | Change |
|---|---|
| `src/seismo/community/verdict.py` | `SYSTEM_PROMPT` rewritten (PM-facing, no-prediction, sarcasm-as-criticism, proportionality, name-collision rule). `verdict_tool_schema()` gained per-field descriptions — the `concerns` one directly targets the zero-concerns failure. |
| `src/seismo/checkpoints/llm.py` | `_complete()` takes optional `provider`/`model` overrides, threaded into `_ollama()` / `_anthropic()`. `complete_community()` passes the community settings. `_COMMUNITY_MAX_TOKENS` 1024 → 2048. |
| `src/seismo/config.py:49` | New `community_llm_provider` + `community_model`, both falling back to the global settings when empty. |
| `.env` / `.env.example` | Community vars set + documented. |

Second session (2026-07-26, after the credit block): the run itself was made safe and fast, since
none of it needs the API.

| File | Change |
|---|---|
| `src/seismo/community/verdict.py` | `--force`+`--limit` rejected (`FORCE_LIMIT_ERROR`); new `redo_before` selection gate; `concurrency` (thread pool over the LLM calls only — the `Session` never leaves the calling thread); `budget_usd` enforcement; `checkpoint` commits per chunk; stats now carry `cost_usd` / tokens / `stopped_reason`. |
| `src/seismo/community/relevance.py` | `_host_anchor()` — a `web` anchor must look like a host to earn its 30 points (landmine #2 root cause). |
| `src/seismo/cli.py` | `--redo-before`, `--concurrency`; wires `llm_budget_usd` and `checkpoint=True`. |
| `src/seismo/community/verdict.py` | Gate on `comment_count > 0`, not thread count — 363 entities were being billed with nothing to summarize (§6.5). `_empty_verdict()` now carries the real kpis. |
| `src/seismo/checkpoints/llm.py` | New `claude_cli` provider — headless `claude -p` on the Claude Code subscription, no API credit (§9). |
| `src/seismo/config.py` | `claude_cli_bin`. |
| `.env` / `.env.example` | `SEISMO_COMMUNITY_LLM_PROVIDER=claude_cli` + `SEISMO_CLAUDE_CLI_BIN`, providers documented with their trade-offs. |
| `tests/test_community.py` | 10 tests: force+limit rejection, redo-before drain, budget stop, concurrency, one-bad-generation isolation, bare-word web anchor, claude_cli fence-parsing + model pinning, non-JSON error surfacing, zero-comment gate. |

**The point of the separate vars:** the discussion summarizer runs on the paid API while
comprehension cards and impact briefs stay on local ollama at $0. `SEISMO_LLM_PROVIDER` is
deliberately still `ollama`.

```
SEISMO_COMMUNITY_LLM_PROVIDER=anthropic
SEISMO_COMMUNITY_MODEL=claude-haiku-4-5
SEISMO_LLM_PROVIDER=ollama          # unchanged — cards/briefs stay local
```

Verified: `complete_card` / `complete_brief` still route through the global provider; only
`complete_community` takes the override.

## 4. Was blocked on API credit — routed around it

The API key authenticates correctly (a bad key gives 401; we get 400) but the account has no
credit: `Your credit balance is too low to access the Anthropic API.` The credit check also gates
`messages.count_tokens`, so there is no free pre-flight either.

Rather than wait, the summarizer now runs **Haiku through the local `claude` CLI** in headless
mode (`SEISMO_COMMUNITY_LLM_PROVIDER=claude_cli`), which bills to the Claude Code subscription
instead of API credit. Quality is identical — same model, same prompt. See §9 for the trade.

Since the plan already covers it, the backlog costs **nothing** to run this way — the trade is time
(~1 hour vs ~10 minutes) and plan usage quota. Buying API credit would be faster and gives
guaranteed-well-formed output, and flipping back is a one-line `.env` change; it is an
optimisation, not a requirement.

> ⚠️ **Rotate the key.** It was pasted into a chat transcript on 2026-07-26. Replace it in `.env`.
> (`.env` is gitignored and untracked — verified.)

## 5. How to run it

Nothing is blocked. The run is one command; it commits every chunk, so it is safe to interrupt and
re-run.

```bash
uv run seismo community-research --source summary --concurrency 8
```

To **redo** entities that already have a verdict (e.g. the 107 old qwen ones, or after a prompt
change), stamp a cutoff and pass it. This terminates, and keeps the superseded rows (§8):

```bash
CUTOFF=$(date -u +%Y-%m-%dT%H:%M:%S)
uv run seismo community-research --source summary --concurrency 8 --redo-before "$CUTOFF"
```

Both respect `llm_budget_usd` and stop with `stopped=llm_budget_usd $N reached` rather than running
past it. Re-run to continue — already-summarized entities are not re-selected, so it picks up where
it left off, and failures are retried (§6.7).

> **On `claude_cli`, the dollar figures are notional.** The run bills nothing: it authenticates
> with the Claude Code Max subscription, and the `cost=$…` the CLI reports is what the same work
> *would have* cost on the API. `SEISMO_LLM_BUDGET_USD` is therefore raised to 500 in `.env` — a
> runaway guard, not a spend cap. **Put it back to 30 if this path is ever switched to the
> `anthropic` provider**, where the dollars are real. The genuine limit on a subscription is the
> plan's usage quota (rolling 5-hour window + weekly caps), which nothing here can measure; if it
> is hit, calls fail, land as `failed` rows, and the next run retries them.

Single entity, for debugging: `--entity-id <id> --force`.

Afterwards, **restart `uv run seismo serve`** so the dashboard picks up the new verdicts.

## 6. Landmines — status

1. ~~**`--force` + `--limit` never terminates.**~~ **Fixed.** The combination is now rejected
   outright (`FORCE_LIMIT_ERROR`, raised by both the CLI and `run_community_synthesis`, so no
   caller can trip it), and `--redo-before <ISO>` replaces it: it selects entities whose newest
   verdict predates the cutoff, so each one leaves the selection as soon as it is re-summarized.
   `--force` is still fine on a single `--entity-id`. This is why the old step 2 (`DELETE FROM
   entity_community_research WHERE source='summary'`) is no longer needed — the append-only
   history in §8 survives a redo instead of being thrown away to make the loop terminate.
2. ~~**HN thread matching pulls in name collisions.**~~ **Fixed at the root, and the risk was far
   smaller than estimated.** The earlier "40.2% of HN titles lack the name → 76 entities at risk"
   was an upper bound; measured, the actual contamination was **one entity**. Cause: relevance
   awards 30 points for matching the `web` anchor, and Echo's `web` anchor is the literal string
   `"echo"` — which matches any text containing that word. That is what pushed four Amazon
   smart-speaker threads to exactly 65 (25 name + 30 web + 5 comments + 5 points).
   - Bucketing all 686 HN threads by score: every thread ≥70 is anchor-matched (github/arxiv/hf)
     and legitimate; **only the 60/65 buckets (7 threads) were name-only matches**, 5 of them
     Echo's.
   - Across every entity carrying a community row, exactly **one** has a `web` anchor at all —
     Echo's, and it is the broken one. So the fix is nearly zero-risk.
   - `_host_anchor()` (`community/relevance.py`) now requires a `web` anchor to be host-shaped
     before it earns anchor credit, and reduces it to the hostname so the match is also more
     reliable. Echo's HN row has been re-collected and is now `not_found` — it drops the one
     genuine Show HN thread along with the four false ones, which is the conservative trade.
   - The `SYSTEM_PROMPT` name-collision rule stays as defence in depth.
3. ~~**`llm_budget_usd` is not enforced on this path.**~~ **Fixed.** The CLI passes
   `settings.llm_budget_usd` into `run_community_synthesis`, which accumulates real per-call
   `cost_usd` and stops the run when the ceiling is reached. Checked once per chunk, so overshoot
   is bounded by one chunk (≤ `concurrency × 4` entities), not by the whole backlog.
4. **Tests are slow, and getting slower — here is the actual reason.** The `clean_db` fixture
   wipes 21 tables per test, including `DELETE FROM raw_events` (39,544 rows / 108 MB and growing
   with every collection run). `test_community.py` + `test_api.py` have **47 tests using it**, so a
   full run is ~47 back-to-back full-table wipes: >15 minutes, up from the "~3 minutes" an earlier
   session recorded. Nothing is hanging; Postgres is working the whole time.
   - **The cost scales with your data**, so it will keep degrading. The fix is to stop deleting
     row-by-row — `TRUNCATE ... CASCADE` is near-constant-time — or to narrow the fixture to the
     tables each test actually touches. Worth doing; it is the main drag on the feedback loop.
   - **Never run two pytest processes at once** against the shared dev Postgres. Both wipe the same
     tables inside their transaction and block on row locks, which looks exactly like a hang.
   - Don't run pytest while a `community-research` run is in flight either, for the same reason.
   - Use `-k` to run a subset. But note: **a `-k`-filtered timing does not extrapolate** — the
     per-test cost is dominated by the fixture, so 10 tests in 5 min means 47 tests in ~25 min, not
     ~5. (Estimated wrong twice this way.)
   - For a change to shared code in `checkpoints/llm.py`, a 2-second dispatch assertion (patch
     `_ollama`/`_claude_cli`, call `complete_card`/`complete_brief`/`complete_community`, check
     which provider each reached) covers the real risk — cards and briefs must stay on local
     ollama — without paying for the fixture at all.
5. **NEW — a third of entities were being billed for nothing.** 363 of 1,123 have threads with
   titles but zero comment bodies. The old gate checked `any(s.threads ...)`, so those reached the
   model, which (correctly) replied in prose asking for the comments — a paid call, a
   `JSONDecodeError`, and a `failed` row that was retried forever. The gate is now on
   `comment_count > 0`; those entities get a free `not_found` verdict whose `kpis` still report the
   threads that were collected. **Fixed.**
6. **NEW — `claude_cli` has no forced tool call**, unlike the `anthropic` provider where a
   malformed response is an API-level impossibility. The schema is asked for in the prompt and the
   reply is parsed. Fence-stripping alone was not enough: replies also arrive prefaced ("Here is
   the verdict:") or annotated after the JSON. `_first_json_object()` now scans for the first
   balanced `{...}`, string- and escape-aware. And because a chat-shaped context makes the model
   treat thin input as a question to clarify, the prompt states plainly that this is a batch call
   with nobody to answer — return `insufficient_data` rather than asking for the comments. Both
   real-world failures verified fixed. **Fixed.**
7. **NEW — a `failed` verdict used to be permanent.** `_persist` stamps `researched_at = now()`,
   which is newer than the source rows, so the staleness filter would never re-select that entity:
   one transient rate-limit or malformed reply locked it out of every future run. `_select_targets`
   now also re-selects entities whose *newest* verdict is `failed`, which is what makes "just run
   the command again" work as the retry mechanism. **Fixed.**

## 9. Why `claude_cli` instead of the API

Both run the same model (Haiku 4.5) with the same prompt, so the *output* is the same. What
differs:

| | `anthropic` | `claude_cli` |
|---|---|---|
| Needs API credit | yes | **no** — uses the Claude Code Max subscription |
| Actually billed for the backlog | ~$4 | **$0** (included in the plan) |
| Reported/notional figure | ~$4 | ~$34 — informational only, nothing is charged |
| Real constraint | dollar balance | plan usage quota (5-hour + weekly caps) |
| Time | ~10 min | ~1 hour |
| Structured output | forced tool call (cannot malform) | prompted + parsed (§6.6) |
| Per-call overhead | none | ~24k tokens of Claude Code scaffolding |

Switching is one line in `.env` (`SEISMO_COMMUNITY_LLM_PROVIDER`). Two implementation details
worth knowing, both measured rather than assumed:

- **The default system prompt is deliberately left in place.** Replacing it with
  `--system-prompt` to cut the scaffolding *doubles* the cost ($0.037 vs $0.016 on an empty
  prompt) because it busts the shared prompt cache — the scaffolding is mostly cache *reads*.
- **`cwd` is a temp dir, not the repo**, or every call would also load this project's `CLAUDE.md`.
  `--strict-mcp-config` likewise keeps MCP servers out of each invocation.

`SEISMO_CLAUDE_CLI_BIN` must be an absolute path for anything under launchd or cron
(`scripts/com.seismograph.daily.plist`) — those do not inherit an interactive `PATH`.

## 7. Cost and time estimates (measured, not guessed)

**Only ~760 of the 1,123 entities are billable at all.** 363 (32%) carry thread *titles* with no
comment bodies — GitHub issues nobody replied to. There is nothing to summarize from a title, and
the model correctly refuses; those calls used to be paid for and then land a `failed` row that was
retried on every subsequent run. They are now gated out before the model is reached (§6.5).

Built the real prompt for the pending entities:

- **Input: 1.11M tokens total** — median 503/entity, p90 ~3,080, max ~7,090.
- **Output: ~150 tokens/entity** observed on the old sparse schema; ~400–500 for the richer one.
- **Cost via `claude_cli` (what we are actually running): $0.** It runs on the Claude Code Max
  subscription. The CLI still *reports* a per-call figure — ~$0.045/entity, ~$34 for the backlog,
  measured at $0.0492 for a 153-comment entity and $0.088 for a batch of 6 — but that is the
  notional API-equivalent, not a charge. What it actually consumes is plan usage quota.
- **Cost via the `anthropic` API for the same work: ~$4** ($1/$5 per MTok on Haiku 4.5). The ~10x
  gap is Claude Code's own scaffolding — ~24k tokens of system prompt and tool definitions ride
  along with every `claude -p` invocation, mostly as cache reads. Halves again via the Batch API
  (needs code changes; the loop is synchronous).
- **Time:** each `claude -p` call takes ~30–60 s (it is a full agent turn, not a bare completion).
  Measured: 6 entities at `--concurrency 6` in 52 s. At `--concurrency 8` the ~760 billable
  entities land around **an hour**. The code has no retry/backoff, so a rate-limited or
  non-JSON entity becomes a `failed` row and is simply re-selected on the next run — re-running
  the command is the retry mechanism.
- **Ongoing:** after the backlog, the daily pass only re-summarizes entities whose discussion
  actually changed (per-source cadence: breakout/accelerating 1d, simmering 3d, fading/dormant
  14d, not_found 7d). That's tens of entities — cents per day.

## 8. Storage & cadence

Verdicts are **append-only** — `_persist()` (`verdict.py:336`) INSERTs a new row each run and never
updates, so the full history of how community opinion evolved is retained. The dossier API and the
dashboard panel read the newest row per entity.

Run `--source summary` daily right after collection. It is idempotent and self-limiting:
`_select_targets()` only picks entities whose newest per-source row is newer than their newest
summary. To re-do everything after a prompt/model change use `--redo-before <ISO>` (§5 step 3),
which terminates and preserves the history; `--force` is for a single `--entity-id` only.
