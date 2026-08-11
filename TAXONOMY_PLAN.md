# Emergent taxonomy — how links get made and how the vocabulary grows

*Plan, not built. Written 2026-08-07. Answers the open question `GRAPH_PLAN.md` left standing and
the linking blocker in `SOURCE_EXPANSION.md`.*

---

## 1. Why this exists — the arithmetic

A wave needs four entities **linked to each other**. Coverage today:

```
18,360 entities
   771 have a comprehension card    →  4.2 %
   283 semantic edges total         →  ~1.5 % of entities touched
```

Those two filters do not add, they **multiply**. Out of 100 new repos in a window: ~4 carded, and
of those ~0 carry an edge. Four are required. That is why `clusters=0`, and it is not a bug in the
detector.

There is a second, sharper reason. In the known convergence (`AGENT_GUARDRAIL_WAVE.md`) six tools
formed a real group whose category **did not exist in the vocabulary**. `seed/categories.yaml` has
`guardrails` and `ai-security`; `assign_category()` is deterministic keyword matching and scattered
all six into `agent-framework` / `rag-framework` instead, because that is the language those
projects use about themselves.

So the vocabulary is not merely incomplete — it is structurally incapable of naming a category that
did not exist when it was written. Every genuinely new thing lands in the wrong drawer by
construction.

## 2. How a link is made

Three steps, and the last two contain no model at all.

**1 — text becomes numbers.** A local embedding model turns a card into a fixed-length vector. Same
text in, same vector out, forever.

```
"tokenfence: middleware that counts tokens and cuts the agent off at a limit"
   → [0.021, -0.44, 0.87, …]   (1024 floats)
```

**2 — two vectors give a distance.** Cosine, computed in Postgres.

```
tokenfence ↔ budgetd      0.19
tokenfence ↔ spendlock    0.23
tokenfence ↔ react-todo   0.91
```

**3 — below the threshold, write an edge.** Arithmetic, no judgment.

The result is a row in the table that already exists. `entity_semantic_edges` carries `model` and
`confidence_score`, so an embedding edge is `model="bge-…"` with the cosine score — sitting beside
LLM-derived rows **without pretending to be the same kind of claim**.

## 2b. What gets embedded — two tiers, and the LLM comes second

The natural assumption is that a model must first produce keywords and summaries for all 18,360
entities before anything can be embedded. It does not, and keywords are the wrong output anyway —
an embedding model consumes prose, not tags, and model-generated tags fragment into near-synonyms
(`cost control` / `budget limiting` / `spend guard`) that never join.

There are two things worth embedding, and the cheap one bootstraps the expensive one.

**Tier 1 — raw collected text. No model, works today, all 18,360 entities.**

The catch is real: a README is mostly packaging. Badges, install instructions, licence boilerplate,
contributor lists. Two tools solving the same problem in different languages have their vectors
dominated by `pip install` versus `cargo add` — the embedding captures how a project is *shipped*,
not what it *is*.

**Tier 2 — the comprehension card, ideally its `problem_statement`.** The noise is already stripped,
so this embeds meaning. It costs one LLM call per entity, and coverage is 4.2% today.

**They compose, and the order is the opposite of the intuition:**

```
1.  embed raw text for everything          free, today, 18,360 entities
        ↓
    a coarse graph — good enough to see WHERE the young entities cluster
        ↓
2.  card only those dense young regions     hundreds, not 9,800
        ↓
3.  embed problem_statement for them        a sharp graph where it matters
```

**The cheap layer chooses who gets the expensive call.** That also answers "how many cards do we
need" without guessing: the coarse graph shows it. Dense around `agent-*` and empty around
`ml-compiler` means card the first and ignore the second.

⚠️ **The rule that keeps tier 1 safe:**

> Raw-text similarity may decide **who gets carded**. It must never decide **who is in a wave**.

Coarse embeddings will link two tutorials more strongly than two real tools, because tutorials are
written alike. That is acceptable for steering attention and unacceptable for a record that claims
independent teams converged. Wave membership forms only from tier-2 edges.

## 3. Scale decides the architecture, not preference

All-pairs over the current universe:

```
18,360 × 18,359 / 2  =  ~168,500,000 pairs
```

No LLM does that at any price. An embedding index does it in seconds. But embeddings measure *"this
text resembles that text"*, and the question that actually matters is *"do these solve the same
problem"* — which is exactly where a language model wins:

```
tokenfence      "middleware that counts tokens"
agent-treasury  "a ledger with hard limits for agents"
```

Different vocabulary, different approach, **same problem**. Embeddings put them far apart; a model
reading both does not.

So neither replaces the other. They sit at different points of a funnel:

```
168,500,000 pairs
      ↓   embeddings — local, free, deterministic
   ~360,000 candidates          (top-k neighbours per entity)
      ↓   threshold cuts the obvious
     ~5,000 ambiguous pairs
      ↓   LLM adjudicates only these
   clusters  →  LLM names the cluster  →  category
```

The model sees roughly **0.003 %** of the volume, and only where the decision is genuinely hard.

**Membership is never a model's call.** The LLM names and adjudicates edge cases; the cluster itself
is arithmetic. That is invariant 4, and it is the line that must not move.

## 4. The inversion

```
today:     category  →  entity          keyword matching against 30 fixed slugs
proposed:  entities  →  cluster  →  name  →  category  →  filter
```

The vocabulary grows **out of the data** instead of being guessed in advance. Applied to the known
case:

```
6 descriptions → embeddings → a cluster forms on its own
                            → "this group has no name in the vocabulary"
                            → named: "agent-distrust tooling"
                            → promoted to a category slug
                            → becomes a facet in /waves
```

That is the same finding the system already produced by hand, arrived at mechanically.

## 5. The promotion rule — the part that keeps this safe

> **Clusters are discovered continuously. Categories are promoted deliberately.**

Cluster boundaries move as data lands. If categories moved with them, the filter
`agent-distrust tooling` would mean one thing in March and another in June — and since the archive
*is* the product, a label whose meaning drifts destroys the thing being sold.

A cluster becomes a category only when **all** of these hold:

| Condition | Why |
|---|---|
| stable across `taxonomy_promote_runs` consecutive runs | one noisy run must not mint vocabulary |
| ≥ `taxonomy_promote_min_members` members | a pair is not a category |
| member set overlap ≥ 0.6 between runs | "stable" must mean the same entities, not the same count |
| no existing category covers ≥ 0.8 of its members | otherwise it is a duplicate of something named |

On promotion it is written into `seed/categories.yaml` **as an ordinary slug with a dated comment**,
by the same file format everything else uses. It is a git edit, reviewable in a diff, revertible.
Nothing appears in the vocabulary without a commit.

This mirrors the merge queue exactly: **proposed automatically, promoted deliberately.**

### Where promoted categories sit in assignment

`assign_category()` matches keywords in file order, and order is priority. A promoted category has
no hand-written keywords, so assignment needs two paths:

1. **Cluster membership** — primary for entities inside a promoted cluster.
2. **Keyword matching** — unchanged, and still the path for everything else.

Cluster membership wins where both apply, because a keyword rule written before the category existed
cannot know about it. The LLM naming step should also propose keywords for the new slug, so the
keyword path catches *future* entities that never make it into the original cluster.

⚠️ Category is the computational key for cohorts and reach. Moving entities between categories moves
their cohorts, which moves velocity percentiles, which moves momentum. **A promotion is a
recalculation, not a rename.** It must be applied at a dated boundary, never retroactively.

Fortunately the machinery for that already exists: `entity_category_history` is time-versioned
(doc 13 A-2) precisely so the category an entity had *at as_of* stays recoverable. A promotion
appends a row; it never overwrites. Replays of past dates keep seeing the old category, which is
what makes this safe to do at all.

## 6. Storage

New: an embedding per entity, in `pgvector`.

```
entity_embeddings
  entity_id     bigint pk → entities.id
  model         text          -- which model produced it; a model change is a new row, not an edit
  dim           int
  embedding     vector(1024)
  source_text   text          -- the exact text embedded, so a vector is reproducible
  computed_at   timestamptz
```

`source_text` matters more than it looks: without it you cannot tell whether a vector is stale
because the card changed or because the model changed, and you would silently compare vectors from
two different inputs.

Cluster and promotion state need their own append-only tables — `taxonomy_clusters`,
`taxonomy_cluster_members`, `taxonomy_promotions` — following the wave tables' shape, including the
`_CLEAR_TABLES` warning in `tests/conftest.py`.

18k vectors is small; an HNSW index handles far more, and it lives in the Postgres already running
rather than a second service.

## 7. Clustering itself

A fixed global threshold is crude — some regions of the space are dense, others sparse. Density-based
clustering (HDBSCAN-shaped) finds variable-density groups and, importantly, **labels noise as noise**
instead of forcing every entity into its nearest cluster.

The pattern *embeddings → cluster → name the cluster* is well-trodden (BERTopic and relatives).
**Borrow the pattern, not necessarily the dependency** — their naming step is keyword-based and
weaker than a model reading the members.

## 8. The long game — the archive is also a training set

Every wave confirmed or rejected is a **labelled example**:

```
"these 6 were a wave"            →  6 positive pairs
"these 5 were not, one team"     →  5 negative pairs
```

Today there are zero labels, so a trained classifier is not an option. After twenty or thirty graded
waves there is a real dataset, and the LLM adjudication step in §3 becomes replaceable by something
cheaper, faster and deterministic.

This is a second reason time compounds here, and a second reason to start recording before the output
looks impressive.

## 9. Acceptance test

Before any of this is trusted: **it must reproduce the six-member guardrail wave from
`AGENT_GUARDRAIL_WAVE.md`.**

If the embedding threshold cannot group those six — whose descriptions genuinely differ — that is a
finding, not a failure, and it means the text being embedded is wrong. The likely fix is embedding
the `problem_statement` field rather than the description (see `LEAD_TIME_PLAN.md` discussion), since
the six share a problem and not a vocabulary.

## 10. Explicit non-goals

- **No LLM decides cluster membership.** Naming and edge-case adjudication only.
- **No category appears without a commit.** Auto-mutating vocabulary breaks the archive.
- **No free-text tags as join keys.** Filter on the closed vocabulary; search on embeddings; never
  filter on model-generated strings, which fragment into thousands of near-synonyms that never match.
- **No retroactive re-categorization.** Promotions apply forward, through
  `entity_category_history`.
- **Do not delete the LLM edge layer.** Embeddings are the dense daily floor; the reasoned edges stay
  as a sparser, higher-judgment layer above.

## 11. Open questions

1. What text gets embedded — card description, `problem_statement`, or both concatenated? §9 suggests
   the answer, but it needs measuring against the known wave.
2. Which local model, and what happens on a model upgrade — re-embed everything, or version and run
   both? (`entity_embeddings.model` exists so both are possible.)
3. Does a promoted category ever get demoted if its cluster dissolves, or does the vocabulary only
   grow? Growing-only is simpler and safer for the archive; it also accumulates dead slugs.
4. Threshold and promotion constants — all guesses until run against real data, and each change
   belongs in `DECISIONS.md`.
