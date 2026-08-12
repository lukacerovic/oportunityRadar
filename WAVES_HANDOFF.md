# Wave Radar — handoff

*Written 2026-08-04. Branch `claude/novi-feature-xtb4lc`. Everything below was built and verified
against a real Postgres 16 in a clean container — migrations applied, tests green, both servers run,
screens rendered. **Never run against real collected data**, because that database was empty.*

Design docs: `WAVE_PLAN.md` (detection) · `LEAD_TIME_PLAN.md` (observers, outcomes, the product).
This file is the practical one: what exists, how to run it, and what to watch for.

---

## 1. What the feature is

Three claims, in order, each measurable:

1. **A wave formed** — N *independent* young entities entered the same problem space inside a short
   window. The only stage in the system that asks a question about a population, not one entity.
2. **Someone saw it earlier** — the earliest authored, timestamped mention in collected text, and
   how many days it predates detection.
3. **It took hold, or it didn't** — measured 90 days later, cohort-relative, from usage data
   already collected. No press, no market data.

The product is the **archive**: a dated record written before the outcome is known and graded after.
A dashboard is reproducible in a month; a multi-year record of dated calls is not.

## 2. Commits on the branch

```
a1f1747  feat(waves): convergence detection, lead time, and cohort-relative outcome
008bbb5  docs: LEAD_TIME_PLAN — state the product and cut v1 to three things
8274929  docs: LEAD_TIME_PLAN — split source discipline into find vs grade
dec9db6  docs: LEAD_TIME_PLAN — early observers and lead-time measurement
683c036  docs: WAVE_PLAN — convergence detection design
```

23 files, ~2,900 lines, all additions. No pull request opened.

## 3. Run it locally

```bash
uv sync
uv run alembic upgrade head          # 0012 -> 0013 (four wave tables)
uv run seismo doctor                 # expect all green

uv run seismo waves                  # detect + observers + outcomes
uv run seismo serve                  # API :8000
cd dashboard && npm run dev          # dashboard :3000
```

Screens: **`/weekly/current`** (what formed, what got graded, what can't be scored) ·
**`/waves`** (faceted list) · **`/waves/{id}`** (one wave as a timeline) · `/entity/{id}`.

Flags: `--as-of ISO_DATE`, `--skip-observers`, `--skip-outcomes`.

⚠️ **Do not run the test suite and the pipeline against the same database at once.** That produced
FK errors twice on 2026-07-26 that looked like real bugs and were pure lock contention.

### See the screen before you have waves

```bash
uv run python scripts/seed_demo_wave.py     # everything it writes is namespaced demo/
uv run seismo waves --as-of 2026-07-20      # detect at formation
uv run seismo waves --as-of 2026-10-20      # later run scores the outcome
uv run python scripts/seed_demo_wave.py --purge
```

That produces exactly the shape of `AGENT_GUARDRAIL_WAVE.md`: 6 members, 2 categories, an
`early_bird` mention 18 days early, and `pypi_downloads_7d` ×775 against a cohort ×2.1 → `took_hold`.

## 4. Read the first real run carefully

`seismo waves` prints a one-line summary. Diagnose from it before touching thresholds:

```
[waves] as_of=… candidates=N clusters=N (below_min=N) collapsed_members=N waves=N (new=N)
```

| What you see | What it means |
|---|---|
| `candidates=0` | Nothing had first evidence inside the last 30 days. Widen `wave_window_days` or check that `collect`/`resolve` ran. |
| `candidates` high, `clusters=0` | The semantic graph is too sparse to link anything — **the expected first result.** See §6. |
| `clusters>0`, `below_min` high | Clusters form but fall under 4 independent members. Look at `collapsed_members` before lowering the floor. |
| `collapsed_members` high | Independence is doing its job — those were the same team. Inspect `wave_members.independence` to confirm it's right. |
| `observations=0` | No HN story mentions any member by name. Expected until the community layer runs. |

Useful queries:

```sql
SELECT id, first_seen, strength, components FROM wave_clusters ORDER BY strength DESC;
SELECT entity_id, link_reason, independence FROM wave_members WHERE wave_id = 1;
SELECT author_handle, lead_days, observed_at FROM wave_observations ORDER BY lead_days DESC;
SELECT metric, verdict, wave_growth, cohort_growth, percentile FROM wave_outcomes;
```

## 5. The knobs — every one is a guess

In `config.py`, overridable via `.env` as `SEISMO_*`:

| Setting | Default | Note |
|---|---|---|
| `wave_window_days` | 30 | The known wave spanned 19 days. |
| `wave_max_age_days` | 180 | Matches the gate's novelty cohort. |
| `wave_min_members` | 4 | Below 4 is coincidence; 6 would have missed the known case. |
| `wave_min_edge_confidence` | 0.5 | Unvalidated. Raise if false links appear. |
| `wave_continuity_overlap` | 0.5 | Unvalidated. |
| `wave_require_momentum` | **False** | Requires a member to have left `dormant`. Off, because on a cold-start DB it silently returns nothing. Turn on once momentum has history. |
| `wave_outcome_horizon_days` | 90 | |
| `wave_outcome_flat_band` | 0.05 | Mirrors `memory/scoring.py`. |

**Record any change in `DECISIONS.md`**, don't edit silently. Calibration needs real data, ideally a
hindcast against known past convergences — it cannot be done from a design branch.

## 6. Known limits — read before concluding the feature is broken

**The semantic graph is the fuel, and the tank is low.** 283 edges over 18,360 entities, from a
one-time snapshot dated 2026-07-25 that does not refresh itself. Waves only form where edges exist.
`GRAPH_PLAN.md` already flags this refresh-cadence problem as blocking its own three consumers; this
is a fourth with the same dependency. **Few waves at first is the expected result, not a bug.**

**Observers currently read one source: `hn`/`story`.** A source qualifies only if it carries an
author *and* a real source time. `hn_discussion` is excluded **because of how the collector writes
it**, not because the data is missing: `_top_comments` flattens a dozen comments into one blob and
stamps `occurred_at` at fetch time, so any lead from it would be measured against our clock.
`TIME_METADATA_AUDIT.md` verified live that the API returns `author`, `created_at` and `points` per
comment — emitting one event per comment lifts the exclusion, and is the largest single expansion
available to this corpus. Adding a source is one entry in `_SOURCES` in `waves/observers.py`.

**Outcome coverage is uneven.** PyPI is Python-only, npm is not collected at all. `unmeasurable` is
a real verdict and must never be read as `faded`.

**Replaying a past date uses today's graph.** Derived edges are not filtered by `created_at`, because
that column records when the model pass ran, not when the relation became true — filtering on it
would make any replay before the last graph rebuild return nothing. Events are still read strictly
at or before `as_of`. Same caveat `momentum_states` already carries by being rewritten each `score`.

**Reverse causation is unsolved.** A writer with a large audience causes the downloads they appear
to predict. Partial defense (not implemented): measure whether the rise persists ~30 days after the
mention spike decays, rather than the spike height. Do not publish an observer's track record until
this is handled.

## 7. Design decisions — please don't re-litigate

- **Clustering goes through a neighbour-label projection**, not edges between candidates. In the
  known case no member pointed at any other; connected components returns 4 disjoint pairs and 0
  waves. This is the single most important line in the design.
- **Category is a weak prior, never the grouping key.** The known wave spanned `agent-framework` and
  `rag-framework` → two different themes. Grouping by either splits it in half.
- **Non-independent members are collapsed, not dropped.** Earliest member represents the team.
  Dropping both would let one shared contributor delete a real wave; dropping neither would let one
  team manufacture one.
- **`first_seen` is never rewritten.** It's the record's birth date and the whole point.
- **No LLM decides membership, strength, or merging** (invariant 4). A naming checkpoint is designed
  but unbuilt, and is cosmetic by construction — a wave renders as `wave-N` without it.
- **Waves do not feed the gate.** That would change the chokepoint the architecture exists to
  protect. Separate decision if ever wanted.
- **Theme is a facet, never a parent.** A wave can carry two themes at once (the known one spanned
  `agent tooling` and `retrieval & memory`), so filtering keeps whole waves rather than descending
  into a branch — a tree would have shown four of its six members and hidden the rest. Themes are
  derived at read time through `vocab.theme_for_category`, so the vocabulary stays the single source
  of truth and re-categorizing needs no migration.
- **An unknown theme matches nothing, not everything.** A typo returning a full list the reader
  believes is filtered is worse than an empty one.

## 8. File map

```
alembic/versions/0015_waves.py     4 tables: clusters, members, observations, outcomes
src/seismo/waves/
  detect.py                        candidates → neighbourhood projection → clusters → strength
  independence.py                  shared person / dependency / shared owner, collapse rule
  continuity.py                    match today's cluster to an existing wave (overlap ≥ 0.5)
  observers.py                     earliest authored mention + lead days; _SOURCES registry
  outcomes.py                      cohort-relative growth → took_hold / flat / faded / unmeasurable
src/seismo/cli.py                  `seismo waves`
  facets.py                        theme/verdict/lead filters over whole waves
src/seismo/api/{app,models}.py     GET /waves (+facets), /waves/{id}, /themes, /weekly/{week}
dashboard/app/waves/               index + detail (timeline, not a node-link graph)
dashboard/app/weekly/[week]/       the weekly read: formed · graded · not scored
dashboard/components/{VerdictChip,WaveFacets}.tsx
scripts/seed_demo_wave.py          namespaced demo data, --purge
tests/test_waves.py                21 tests
```

`tests/conftest.py` — the four wave tables are in `_CLEAR_TABLES`, dependents before parents. Any new
table with an `entities`/`raw_events` FK must go there too; this has broken the suite three times.

## 9. Tests

```bash
uv run pytest tests/test_waves.py -q                          # 26 passed
uv run pytest -q -m "not hindcast and not llm_local"          # 286 passed
uv run ruff check && uv run mypy src
```

The acceptance test is `test_detects_the_guardrail_wave`: six members, zero edges between them, two
categories → exactly one wave. **Any implementation that clusters on direct edges or on shared
category fails it.** There is one negative fixture per independence check.

⚠️ The repo carries pre-existing lint/format drift unrelated to this work: `ruff format` rewrites
~22 files, and `ruff check` fails on `alembic/versions/0011_community_research.py` (a 129-char
docstring line). Both predate this branch, so CI is already red on `main`. Left alone deliberately
rather than folded in here — worth a separate formatting-only commit.

## 10. What to do next, in order

1. **Run the community layer.** `src/seismo/community/` is complete and has never run
   (`entity_community_research`, 0 rows). It is the largest source of authored, timestamped text
   already wired in, and step 2 of the product has almost nothing to search without it.
2. **Run `seismo waves` against real data** and read §4 before changing any threshold.
3. **Calibrate**, and record each change in `DECISIONS.md`.
4. **Build the Substack collector** — recorded GO in `DECISIONS.md` 2026-07-23, never built. The only
   pure-commentary surface in the design, and the natural second entry in `_SOURCES`.

Deliberately not built, and none of it blocks the above: press timestamps (`LEAD_TIME_PLAN.md` stage
2), market data and tickers (stage 3), the frozen-`as_of` council role, cross-platform observer
identity, and LLM wave labels.
