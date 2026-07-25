# `feature/signaltracker-port` — commit-by-commit summary

*Written 2026-07-25 before squashing the branch onto `main` as a single commit. Each entry below
is a short summary of one commit's actual content, kept here since that granularity disappears
once the branch collapses to one commit. Oldest first.*

1. **`dd29fa9` checkpoints: claude_cli LLM provider + complete_triage** — added `claude_cli` as a
   fourth pluggable LLM provider (subprocess call to the `claude` binary) alongside
   mock/ollama/anthropic, plus `complete_triage()` for the discovery-triage checkpoint.
2. **`fb21462` feat(collectors): add PyPI collector (Feature 5)** — fifth evidence-type collector;
   pulls package metadata/download signals from PyPI.
3. **`0b8cd37` feat(graph): typed entity-graph edges (built_by/cited/depends_on)** — `derive-edges`
   CLI + `entity_graph_edges` table, the deterministic relation spine (every row justified by
   raw_event ids — never LLM-reasoned).
4. **`4a7d08c` feat(trajectory): hype-gap signal (Feature 2)** — `attention_p - adoption_p`
   metric: high attention without confirmed usage.
5. **`5e0c359` feat(triage): continuous discovery triage (Feature 6)** — automated triage pass
   over freshly-discovered entities.
6. **`fde5c74` test(phase0): market-source spike fixtures + go/no-go verdicts** — spike-tested
   OpenRouter/Reddit/Substack as candidate new sources against live endpoints; verdicts + fixtures
   only, no production code (logged in `DECISIONS.md`).
7. **`de84e1b` chore: clear pre-existing ruff debt (22 findings, gate now green)** — lint cleanup
   unrelated to the above features, no behavior change.
8. **`898f280` feat(collectors): OpenRouter usage evidence, anchored to existing entities** — new
   `OpenRouterCollector` (model listings + weekly rankings) and the `or_tokens_wk` metric. The
   real point: `identity/anchors.py` routes an OpenRouter model onto its existing HF entity (if
   open-weight) or the same `web:` entity an HN launch already minted (by display name) — so
   paid-inference usage lands on the same entity row as GitHub/HN evidence instead of an orphan.
9. **`08264b5` feat(graph): persist reasoned semantic edges in Postgres, drop derived briefs** —
   built a knowledge graph over ~1,938 signal-bearing entities via graphify; kept only the 283
   *reasoned* (`semantically_similar_to`/`conceptually_related_to`) edges in a new
   `entity_semantic_edges` table, deliberately separate from the deterministic
   `entity_graph_edges` spine. Deleted the 7.6MB of derived brief markdown files that made the
   graph (regenerable from Postgres in ~40s) and gitignored both scratch directories.
10. **`0f1fc59` fix(dashboard): cluster overwhelmed Activity/Gate lists, correct evidence unit
    label** — the `/changes/[day]` and `/gate/[week]` pages rendered 300–1000+ row flat lists with
    no grouping; added category-based clustering + a client-side filter (`GroupedList.tsx`).
    Also fixed `EvidenceList.tsx` mislabeling OpenRouter's token counts as "pts/dl" (a leftover
    from when evidence was only HN points or HF downloads) — added an explicit `unit` field per
    evidence source instead of guessing.
11. **`9a13cd2` feat(checkpoints): council review — three independent perspectives on a brief** —
    new checkpoint (`council.py`): three separate LLM calls (skeptic / evidence_auditor /
    mechanism_reviewer) judge an already-drafted impact brief independently, aggregated by a
    deterministic majority vote (never a synthesizing LLM call). Scoped to the top N entities by
    momentum, independent of the weekly significance gate's own budget. Surfaced on `/brief/[id]`
    with an honest empty state when a brief hasn't been reviewed yet.
12. **`7394d1f` docs: log dashboard overwhelm fix + council review in HANDOFF (§32)** — session
    log entry, no code.
13. **`f756cda` fix(dashboard): show which model authored each council verdict** — the council UI
    showed stance/reasoning but not which model produced it; added the `model` label per verdict
    card (provenance matters more than usual here — see the qwen-vs-Fable comprehension-card
    comparison this session surfaced).
14. **`957da73` docs: write the graph-integration plan before it gets lost** — added
    `GRAPH_PLAN.md`: `entity_semantic_edges`/`graphify-out` are stored but have zero consumers
    anywhere in the codebase (verified by grep); the plan records the three concrete places the
    graph would pay off, in cost order, plus the refresh-cadence problem blocking all three.
15. **code review pass (Opus + Codex, independent) — fixes, before squashing to `main`.** Two
    reviewers ran against the full 14-commit diff in parallel (Opus as a background subagent,
    Codex live in a herdr-managed pane). Fixed everything both confirmed or one confirmed and I
    verified directly:
    - **`council.py`**: a failed verdict generation was being persisted as a real "watch" row
      (the code's own comment claimed the opposite — no row meant no retry, but a row *was*
      always stored); fixed to skip storage on validation failure so retries actually happen.
      `_top_by_momentum` had no `day <= as_of` filter — a hindcast run could rank by momentum
      that hadn't happened yet; fixed.
    - **Layering**: `api/app.py` was importing `checkpoints.council`, transitively loading the
      entire LLM-provider chain (`impact.py`, `llm.py`) into the web server for 6 lines of vote-
      counting logic. Extracted `aggregate_stance` into a new leaf module
      (`checkpoints/council_vote.py`, zero other imports) — verified via `sys.modules` that the
      API process no longer loads anything past that one leaf file.
    - **`llm.py`**: a failed `claude_cli` call was tagged with the *same* model string as a real
      generation — the exact bug that mislabeled a comprehension-card version earlier this
      session (HANDOFF §30). Failed calls now tag `claude_cli:fallback`, distinct from a real one.
    - **`health.py`**: `claude_cli` was a valid provider (added in an earlier commit on this same
      branch) but `seismo doctor` didn't recognize it — `SEISMO_LLM_PROVIDER=claude_cli doctor`
      failed "unknown provider" (found independently by Codex). `CORE_TABLES` was also missing 7
      tables — 3 from earlier migrations (`changes_daily`, `calibration_snapshots`,
      `hindcast_runs`) and all 4 new ones from this branch — so `doctor`'s schema check couldn't
      catch a missing table from any of them.
    - **`triage.py`** (pre-existing feature from before this session, not yet wired into
      `daily.sh` or ever run — confirmed 0 rows in `discovery_triage_decisions`): the deterministic
      fallback ignored PyPI downloads entirely (`_threshold_track` never received the value this
      same branch's PyPI collector produces — the two features silently canceled each other), and
      a candidate with zero metrics data got archived outright with no re-entry path (`entity_id`
      is unique in the decisions table, so one bad zero-information judgment is permanent). Fixed
      both: PyPI downloads now pass their own threshold check, and a zero-metrics candidate is
      deferred (left un-decided) rather than archived — unless the AI path already reasoned a
      decision from qualitative facts alone, which it's designed to do.
    - **`graph/edges.py`**: `derive_edges` claims "pure and as-of correct" but two of its three
      lookups (`_load_anchor_map`, `_pypi_lookup`) read every entity with no `created_at <= as_of`
      bound — a hindcast could mint a deterministic-spine edge to an entity that didn't exist yet
      at that instant. Both now filter on `as_of`.
    - **`api/app.py`**: `/changes/{day}` grouped by *today's* `entities.category`, not what the
      category was on that historical day — every other analytical read in the file uses
      `category_asof`. Fixed to resolve category per entity as of end-of-day for the requested
      date (deduped per entity_id, verified fast: 372 rows in ~0.25s).
    - **`scripts/export_briefs.py`**: `--out` did an unguarded `shutil.rmtree` — a typo'd path
      (or `.`) would silently delete it. Added a refusal for cwd/home/repo-root and for any
      directory that doesn't look like a prior brief export, plus `--force` to override.
    - **`dashboard/components/GroupedList.tsx`**: `<details open={...}>` was a React-controlled
      prop with no way to stay in sync with a user manually toggling the native element — fixed
      by keying on the computed default so a search-state change remounts instead of reconciling
      against a possibly-stale manual toggle.
    - **`models.py`**: `EntitySemanticEdge`/`CouncilVerdict` were missing from `__all__`.

    **Not fixed, flagged instead of unilaterally redesigned** (both pre-existing, from before this
    session, and genuine architecture/product decisions rather than mechanical bugs): council.py's
    `_top_by_momentum` computes its own ranking rather than consuming one the gate already
    produced — a real "checkpoints never rank" tension Codex raised, but the momentum-independent-
    of-the-gate population was an explicit choice made earlier this session, not an oversight, so
    it's noted rather than reverted. Council also has no budget ceiling matching `run_brief`'s
    (A-12) — lower urgency given the stated manual/direct-authored usage pattern, but real if
    someone points it at a live provider with a large `--top`. The hype-gap signal's
    adoption-defaults-to-0.0 semantics (flags most HN/GitHub-only entities as "hype" since they
    have no adoption metric at all, not because adoption was measured and thin) is a signal-quality
    nuance needing product judgment, not a bug.

    Full test suite: 213 passed, 0 failed, after all of the above (1h10m — I/O-bound against the
    real dev Postgres, not a slow test).
16. **`feat(dashboard): Gated filter on Radar`** — a "📋 Gated" toggle next to the existing state
    pills, filtering the whole grid to entities that have ever passed the significance gate
    (`gate_decisions.decision = 'pass'`, as-of correct). A small 📋 badge on each card shows gated
    status ambiently even without the filter active. Built because "🔥 Taking off" (momentum-only)
    and the gate (momentum × reach × novelty, budgeted, audited) look similar but diverge in
    practice — verified live that none of today's top-5 breakout entities have ever passed the
    gate. `/gate/[week]` stays as the detailed weekly audit view; this just covers the common
    "show me what's significant" case in one click.

## Net effect on the branch

Two new collectors (PyPI, OpenRouter) with an identity-anchoring mechanism that correlates paid
usage back to existing entities; a deterministic relation graph (`entity_graph_edges`) plus a
separate, clearly-labeled LLM-reasoned relation graph (`entity_semantic_edges`); a third LLM
checkpoint (council review) that adds independent scrutiny to impact briefs without ever letting
an LLM judge its own or another LLM's output unchallenged; two real dashboard UX fixes found by
actually running the app; a third UX addition (the Radar "Gated" filter) built from directly
comparing two similar-looking dashboard features; two planning docs (`DECISIONS.md` additions,
`GRAPH_PLAN.md`); and an independent two-reviewer (Opus + Codex) code-review pass across the whole
branch before it reaches `main`, fixing real bugs both in this session's own new code and three
well-scoped, test-verified fixes to pre-existing code from earlier sessions.
