# Lead time and early observers

*Plan, not built. Written 2026-08-04, branch `claude/novi-feature-xtb4lc`. Sits downstream of
`WAVE_PLAN.md`: a wave says several people started at once; this asks **who saw it first, how early,
and did it matter.***

---

## The claim this feature exists to make

```
Wave "agent-distrust tooling" first detected     2026-07-02
Earliest discussion found in collected text      2026-06-14   (HN, one comment)
First trade-press coverage                       2026-09-14
Lead over press: 92 days
```

That is the whole product in four lines. It is falsifiable, it needs no market data, and no
competitor publishes it. `COMPETITIVE_LANDSCAPE.md` found that everyone ingesting developer signal
uses it to source deals; nobody reports how early they saw a category form.

## Why lead time and not a price call

The system's stated position — repeated in the idea spec's explicit non-goals, in `ARCHITECTURE.md`,
and verbatim inside the impact checkpoint's system prompt (`impact.py:39`, *"You explain exposure;
you never predict prices. No price targets, no buy/sell language"*) — is that it explains exposure
and never predicts prices.

Lead time keeps that position intact and still answers "did we see something real":

- **A date is a date.** Either the observation predates the coverage or it doesn't. No model, no
  confounders, no attribution argument.
- **Market movement is confounded** by earnings, rates, sector rotation — the things we openly cannot
  predict. Lead time is confounded by nothing.

Market-adjusted measurement is stage 3 below, deliberately last, and deliberately framed as
*residual co-movement consistent with a dated thesis* — never as a price call.

## Source discipline — the rule that keeps this from sprawling

The temptation with a feature like this is to bolt on more sources. The constraint is not "how
many" but **which job a source does**, and there are exactly two:

> **Job 1 — who and when.** Finding observers requires an author and a timestamp.
> **Job 2 — did it turn out real.** Grading observers requires measurable adoption, and here an
> author is irrelevant. Text cannot grade itself.

| Source | Carries | Job 1 (find) | Job 2 (grade) |
|---|---|---|---|
| HN comments and threads | author + timestamp | **Yes** — already collected | no |
| Substack posts | author + timestamp | **Yes** — approved, not built (below) | no |
| GitHub README, HF model card, arXiv abstract | artifacts | **No.** They say what was built, not who understood it first. | partial (as entity text) |
| PyPI downloads, HF, OpenRouter tokens, stars | counts | **No.** No author, no opinion. | **Yes — the only thing that works** |

A count will never tell you who was right. It is the only thing that can tell you whether what they
pointed at actually took hold. Both halves are required and neither substitutes for the other.

Under that rule, this feature needs **one** new source for job 1, everything for job 2 is already
collected, and most of what it needs is already paid for and idle.

### Already built, never run

`src/seismo/community/` is complete — 11 modules covering GitHub discussions, Hacker News, and
Hugging Face, with relevance filtering, summarization, and a cross-source verdict. `STATE.md` records
`entity_community_research` at **0 rows**.

**Run this before adding anything.** It is the largest single source of authored, timestamped text
already wired into the system.

### Approved, never built

`DECISIONS.md` (2026-07-23) records Substack as a **GO** after live probing: curated feeds return
200, parse with stdlib `xml.etree`, and alias matching produced zero false positives across 60 items
× 10 aliases. The planned metric was `substack_mentions`, rolling 7d, `evidence_type="attention"`.

It is the only pure-commentary surface in the whole design. Everything else is artifact text. For a
feature about *writers*, that makes it the one source worth building — and the decision to build it
was already taken, it just never happened.

**Nothing else gets added for this feature.** Not Reddit (`DECISIONS.md` recorded it NO-GO keyless —
403 bot-wall, RSS carries no scores, 429 after ~8 requests). Not Twitter/X. Not news APIs beyond what
stage 2 needs for the press timestamp. The discipline that killed Reddit and OpenRouter applies here:
*drop, don't work around*.

## The gap that is not a source gap

The system tracks **builders**: `built_by` edges to person entities, plus Wikidata person enrichment.

It does not track **observers** — people who write about things. The same person is in the database
if they committed code, and invisible if they wrote the sharpest analysis of the same technology
three months earlier.

That is a missing entity kind, not a missing feed. An observer needs:

- a durable identity across handles (HN username, Substack author, GitHub login) — the existing
  `identity/anchors.py` pattern extends naturally (`hn:username`, `substack:pub/author`)
- a record of what they wrote about, and **when**, relative to when the system detected the thing
- resolution that is queued and audited, never silent, exactly like entity merges — a wrong observer
  merge attributes one person's foresight to another

⚠️ Observer resolution is *harder* than entity resolution, not easier. A handle is not a person, the
same handle across platforms is not evidence of the same human, and being wrong here is worse than
being silent. **v1 should not merge across platforms at all** — track per-handle records and leave
cross-platform identity as an explicit later decision.

## Three stages, in order

### Stage 1 — Lead time over collected text *(build first)*

For a detected wave or gate-passed entity, find the earliest authored, timestamped text in the
collected corpus that discusses it, and report the gap between that and detection.

Purely deterministic: a text search over `raw_events` with `occurred_at`, plus the existing
`content_sanity_checks` to exclude spam so a bot post doesn't win "earliest mention".

Output per wave: earliest mention, its author handle, its source, and the lead in days.

**This needs zero new sources.** It measures what the system already has.

### Stage 1b — Grading an observer with usage data *(no press, no market data)*

A mention is an implicit forward claim: *this thing matters*. That claim is measurable entirely
inside the existing system, which means the observer record does **not** have to wait for stages 2
and 3.

```
2026-06-14   HN comment mentions termaxa        →     40 downloads/wk
2026-07-02   system detects the wave
2026-12-14   termaxa                            → 31,000 downloads/wk

             cohort (agent-framework, 0–180d) median growth:  ×2.1
             termaxa:                                         ×775   → percentile 0.98
```

**Cohort-relative, never absolute** — the same principle that makes momentum meaningful
(`trajectory/cohorts.py`). Mentioning LangChain is not foresight. Mentioning something at the bottom
of its cohort that then climbs is.

This is not new machinery. `memory/scoring.py` already auto-evaluates `source='system'` observables
by comparing a metric's actual movement against a predicted direction, with `_FLAT_BAND = 0.05`
separating direction from noise. Grading a mention is the same operation with a different subject.

⚠️ **Reverse causation is the central threat.** A writer with a large audience *causes* the
downloads they appear to predict, and would score as prescient purely on reach. Partial defense:
measure whether the rise **persists** after the mention spike decays (e.g. level at +30d versus the
spike itself), not the height of the spike. This does not fully solve it and should be stated as a
known limitation wherever an observer score is displayed.

⚠️ **Coverage is uneven.** PyPI is Python-only; HF covers models; npm is not collected at all. A
wave made of JS tooling has no usage signal to grade against. Absent metrics must read as
*unmeasurable*, never as *did not take hold*.

### Stage 2 — Press lead time

The claim gets far stronger with an outside reference point: the first time mainstream or trade press
covered the category.

This needs a press timestamp, and that is a **Phase-0 source probe** in the `DECISIONS.md` style
before any code: probe candidates, record verdicts with fixtures, drop rather than work around.
Explicitly out of scope until that probe is written up.

### Stage 3 — Market-adjusted residual *(last, and optional)*

Only after 1 and 2 work. Event-study shaped, not a price call:

```
CRWD over the window                +9%
market over the same window         −3%   ← not ours
sector over the same window         −2%   ← not ours
──────────────────────────────────────────
unexplained residual                +4%   ← the only figure ever quoted
```

The subtracted terms are the things we openly cannot predict. The residual is reported as
**co-movement consistent with a dated thesis**, never as causation and never as a recommendation.

Requires a market data source, which does not exist in the system today — and note that
`exposure_map/` financials are placeholders that `STATE.md` says never to quote as real. Same
Phase-0 discipline applies.

**Honest limit:** with 24 briefs and ~18 council verdicts, this is statistically underpowered and
will stay that way for a long time. For the first year it is a dated diary, not evidence. A diary
that grades itself becomes evidence eventually; a diary that overclaims never does.

## The reasoning lens — and the trap it must survive

The attractive idea: a viewpoint that reasons the way the people who called it early reasoned.

**The trap is survivorship bias.** Who was right is only knowable afterward. Hundreds of confident
predictions were written; a handful landed. Studying only the ones that landed teaches their *style*,
not their *method* — and the style is identical in the ones that failed. Built naively, this produces
a machine that generates confident hindsight.

Two defenses, both structural rather than instructional:

**1. Freeze time mechanically.** Invariant 2 already requires every downstream computation to read
only events with `occurred_at <= as_of`. So the lens runs with `as_of` pinned to the detection date
and **physically cannot see** what happened later. It is not asked to pretend it doesn't know — it is
not given the data. This is the same substrate as the time-machine idea, and it is what makes the
whole lens honest rather than theatrical.

**2. Score specificity, not correctness.** The measurable virtue of a good early call is that it was
dated, concrete, mechanism-based, and falsifiable — not that it turned out right. The brief contract
already enforces exactly this shape: `counter_mechanism` required, at least one `Observable` with a
`direction_if_thesis_holds` and a `horizon`. Grade early writing on the same bar.

*Being right* cannot be measured in advance. *Being precise enough to be wrong* can. That distinction
is the entire defense.

### Where it hooks in

As a fourth council role, not a new subsystem. `checkpoints/council.py` already runs three
independent roles (`skeptic`, `evidence_auditor`, `mechanism_reviewer`) with deterministic majority
aggregation in `council_vote.py` — never a synthesizing 4th LLM call, so cost doesn't compound.

The new role — `early_observer` — is prompted with the frozen-`as_of` pack and asks one question:

> Given only what is known as of this date and nothing after it, what would someone looking six
> months ahead notice here that isn't obvious from the artifact alone?

Its answer is stored with the date it was written, and graded later against the same falsifiability
bar as everything else.

⚠️ Adding a fourth voter changes majority arithmetic — three roles split 2–1, four can split 2–2.
`council_vote.py` deliberately leaves a 3-way split as `split` rather than smoothing it into fake
consensus. Either keep this role advisory and outside the vote (recommended for v1), or decide the
tie rule explicitly and record it in `DECISIONS.md`.

## Explicit non-goals

- **No price targets, no buy/sell language.** Unchanged from the idea spec.
- **No imitation of named individuals.** The lens reasons from frozen evidence; it does not
  impersonate a writer or claim to reproduce anyone's thinking.
- **No cross-platform observer merging in v1.** Per-handle only.
- **No new sources beyond Substack**, and that one only because it was already approved and is the
  only pure-commentary surface.
- **No automated grading of the system by the system.** DR-09.2 stands: the verdict is a ritual with
  a UI, because grading the system with the system is worthless.

## Open questions

1. Does "earliest mention" require a relevance bar beyond keyword match? A passing reference in an
   unrelated HN thread is technically earliest and substantively meaningless. The `community/`
   relevance module may already solve this — check before building anything new.
2. Should lead time attach to a wave, an entity, or both? A wave is the more interesting claim; an
   entity is the easier measurement.
3. Is an observer's track record ever surfaced publicly? "This handle has been early 4 times" is a
   compelling artifact and also a claim about a real person, made from thin evidence. Default to no
   until the sample is large enough to survive being wrong in public.
