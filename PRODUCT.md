# The product — what we are building and why

*Written 2026-08-07 on branch `claude/novi-feature-xtb4lc`. This is the entry point: what the thing
is, who it is for, and what has to be true for it to work. The mechanism lives in `WAVE_PLAN.md`,
`LEAD_TIME_PLAN.md`, `TAXONOMY_PLAN.md` and `SOURCE_EXPANSION.md`; this file is why any of it
matters.*

---

## 1. In one paragraph

A dated public record of technology categories forming in the IT sector — when each one formed, who
saw it first, how early, and whether it turned out to be real. Every entry is written **before the
outcome is known** and graded afterwards against measurements the system already collects. The
archive is the product; the dashboard is only how you read it.

## 2. What "trend" means here

Not what is popular. Everyone measures popularity.

> **A trend is several unrelated teams independently starting on the same thing inside a short
> window.**

That definition is the whole product. One repo with 5,000 stars is news. Four repos from four teams
who do not know each other exist is **evidence that something is changing** — and nobody else
measures it, because it cannot be seen by watching any single project.

It also explains the system's most important refusal: five microservices from one company look
identical to convergence and are not convergence. The independence check is not an optimization,
it is the definition being enforced.

## 3. Three timestamps turn an opinion into a claim

```
14 Sep    someone on HN: "my agent burned $400 overnight, nobody is solving this"
21 Oct    four independent tools exist            ← THE TREND FORMS
14 Jan    +90d: downloads ×34 against a cohort ×2.1   ← WE WERE RIGHT
```

Without dates this is commentary. With dates it is a record that could have been wrong.

## 4. Who uses it, and how often

**Weekly, five minutes.** If anyone opens it daily, it was built wrong.

| Reader | What they do with it |
|---|---|
| **Analyst / investor** | Sees a category forming, checks who is building it and where those people work, then goes looking at which public companies it touches. The app never says what to buy — it says **where to look, months before it is obvious.** |
| **Founder / builder** | Sees four teams doing what they are doing. Accelerates, pivots, or stops. Better to learn that in October than in January. |
| **Product / strategy** | Sees something forming in their category that does not have a name yet, ahead of the conference circuit. |

## 5. The lifecycle, end to end

Worked on a single example — *"spend guards for agents"*.

**14 Sep — nothing has happened.** A comment under an unrelated thread: *"my agent burned $400
overnight."* Forty-seven upvotes, forgotten in two days. **The app says nothing** — but it records
the comment, with its author and its date.

**2–15 Oct — three repos appear.** `tokenfence`, `budgetd`, `spendlock`. **The app still says
nothing.** Three is not a wave. The silence is deliberate: every competing tool would have sent
three separate "trending repo" alerts, which a reader receives as three unrelated trivia and
forgets.

**21 Oct — the fourth, and the trend exists.** `agent-treasury`. Independence passes: four different
owners, no shared authors, no dependency between them. The app writes the record, then looks
backwards through everything it ever collected and finds the September comment.

```
WAVE #41   spend guards for agents
formed 21 Oct · 4 independent teams · 19-day window
earliest mention 14 Sep by kmoss (HN) — 37 days before us
```

**26 Oct — a human reads it.** Not "`tokenfence` exists" — that is noise. But *four unconnected
people independently reached the same conclusion in three weeks*, which no single repo can say. They
click through, see who builds them, read the September comment, and **then go do something outside
the app.** That is the point.

**Nov–Jan — the app does nothing visible.** A fifth member may join; `first_seen` does not move. The
reader has long forgotten. **The app has not.**

**19 Jan — the horizon, and the system grades itself.**

```
📈 GRADED   spend guards for agents (formed 21 Oct)
   +90d:  took_hold — ×34 against a cohort ×2.1
```

The claim written in October, when nothing was known, is now settled. **The opposite verdict is
worth exactly as much:**

```
📉 GRADED   faded — ×1.4 against a cohort ×2.1
```

Four teams started, nobody adopted. That is a finding too, and it stays on the page. Competitors
delete their misses; here a miss is permanent.

**Six months on — the thing that cannot be copied.**

```
14 waves · 9 graded · 6 right · 2 wrong · 1 undecided
median lead over first public mention: 29 days
```

Not because it is hard to build, but because **a competitor starting later cannot retroactively have
made those calls.** Time is the only input that cannot be bought.

## 6. What this is not

| Not | Because |
|---|---|
| an AI news digest | news is the end of the story; we report the beginning |
| a stock picker | it explains exposure and never predicts prices — unchanged |
| a startup-sourcing tool | it looks for patterns, not companies |
| a daily dashboard | weekly, five minutes, or it was built wrong |

**And the honest limit that defines the product: it does not predict, it dates.** It cannot tell you
something is about to exist. It can tell you it *does* exist, before anyone wrote about it, and later
prove it was right. That is a weaker claim than prediction and the only one that survives contact
with reality.

## 7. The engine

Every view — the weekly read, the wave page, the entity page, any model-written summary — is a
projection of **one assembled dossier**. The pattern already exists in the codebase as
`checkpoints/impact_pack.py`: pure, deterministic, bounded, versioned, as-of correct. It simply only
serves one consumer today and only accepts an entity.

An insight has six slots:

| Slot | Source |
|---|---|
| **What it is** | comprehension card |
| **Who is behind it** | `built_by` → person → `employed_by` (Wikidata) |
| **When, and who saw it earlier** | `first_seen`, `wave_observations` |
| **How much — against its peers** | cohort percentile, never absolute |
| **What it moves with** | wave members, semantic neighbours |
| **What would prove it wrong** | `Observable`, `counter_mechanism` |

**A dossier renders absence explicitly.** A slot that reads *"no author data — `enrich-contributors`
is not in `daily.sh`"* is honest and still useful. A slot silently omitted is a lie, because the
reader believes they saw everything. This is also the best diagnostic available: the gaps are the
fix-list, on screen, ordered by how much they actually hurt.

**The model writes sentences; it never chooses facts.** Assembly is deterministic SQL. Same
relationship as `impact_pack` → `impact` checkpoint.

## 8. What has to be true for it to work

A wave needs four entities linked to each other. Two coverage filters stand in the way, and they
**multiply rather than add**:

```
18,360 entities
   771 have a card    →  4.2 %
   283 semantic edges →  ~1.5 % of entities touched

100 new repos → ~4 carded → ~0 of those carry an edge → 4 required → zero waves
```

That is why detection currently returns nothing, and it is not a bug in the detector.

Neither fix works alone. **Embeddings** draw links for every carded entity — but linking four
entities is still four. **Carding** produces descriptions — but nobody draws lines between them.
Both, or nothing.

`scripts/measure_readiness.py` replaces every number above with a measurement. **Run it before
deciding anything**; the count of *young, in-window, uncarded* entities is the one number that says
whether this is an afternoon's work or a budget decision.

## 9. Where it stands

**Built, tested, running** — convergence detection with independence checks, lead-time search,
cohort-relative outcome grading, `/waves`, `/waves/{id}`, `/weekly`, theme facets. 26 tests on the
wave layer, 286 in the CI subset.

**Built and never run** — `src/seismo/community/`, the largest source of authored timestamped text
in the system (`entity_community_research`: 0 rows).

**Approved and never built** — the Substack collector (`DECISIONS.md`, 2026-07-23).

**Not wired** — `track --source pypi`, `enrich-contributors` and `enrich-pypi` are absent from
`daily.sh`, which alone is why every outcome reads `unmeasurable` and why two of three independence
checks never fire.

**Designed, not built** — the embedding layer, emergent taxonomy, `problem_statement`, the track
record page.

## 10. Build order

| # | Step | Needs measurement first? |
|---|---|---|
| 1 | three lines into `daily.sh`; widen GitHub `TOPICS`; run the community layer | no — do it today |
| 2 | `problem_statement` in the comprehend contract | no |
| 3 | email ecosyste.ms about licensing; run `probe_sources.py` | no — zero code, largest unlock |
| 4 | embeddings + `pgvector`, coarse tier over everything | **yes** |
| 5 | card the dense young regions the coarse tier reveals | yes |
| 6 | clustering, naming, category promotion | yes |
| 7 | HN comments behind a relevance pre-filter | no, but costs sanity budget |
| 8 | npm / deps.dev adoption metrics | no |
| 9 | the track record page | after 3–4 waves are graded |

Steps 1–3 are roughly a day between them and need no new information. **Step 4 is the one that
decides whether the product exists at all.**

## 11. Rules that do not bend

1. **Every claim traces to a raw event.** No unauditable middleman, ever — which is why resold APIs
   are out and first-party aggregators are in.
2. **No model decides membership.** It names clusters and adjudicates ambiguous pairs. Membership is
   arithmetic. (Invariant 4.)
3. **`first_seen` is never rewritten.** It is the record's birth date and the whole point.
4. **Categories are promoted deliberately, never auto-minted.** A label whose meaning drifts destroys
   an archive that *is* the product.
5. **`unmeasurable` is never rendered as failure.** Absence of evidence is not evidence of absence.
6. **Misses stay on the page.** A record that hides its errors is worth less than no record.
7. **Coarse similarity may choose who gets carded; never who is in a wave.**

## 12. Open decisions

1. **Does the weekly read leave the app** (email/RSS) or stay a page? Page first — email is delivery
   of something the page must compute anyway.
2. **Is an observer's track record ever published?** Not until reverse causation is handled: a writer
   with a large audience causes the adoption they appear to predict.
3. **Does the market layer ever ship?** If it does, as residual co-movement against a dated thesis —
   never as a price call. Half the bridge already exists unused in the Wikidata layer;
   `KEPT_PROPS` omits `P249`/`P414`.
4. **All thresholds** — eight wave settings, plus embedding and promotion constants. Every one a
   guess until run against real data, and every change belongs in `DECISIONS.md`.
