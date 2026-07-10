# Seismograph — 05 Comprehension Layer (LLM Checkpoint 1)

*Implements idea-spec §5 Layer 3. Given an entity's evidence, produce structured claims + a readable summary. One of exactly two modules allowed to call the Anthropic API.*

> **Amended by doc 13:** **A-13** (the Anthropic call goes through a pluggable provider in `checkpoints/llm.py` — `mock` for CI, **local `ollama`** for dev/plumbing tests, `anthropic` for prod; build this whole checkpoint against Ollama/mock at $0, the API key is not needed until H2/go-live); **A-8** (model from config `SEISMO_MODEL_LIVE`; hindcast forces the pinned `SEISMO_MODEL_HINDCAST`); **A-12** (on LLM budget-ceiling the call is not attempted and the card is marked **`pending`** — distinct from `failed`, which is reserved for post-retry *validation* errors — then retried next window; `doctor` alerts if `pending` persists >48h).

---

## DR-05.1 — Model: Claude Sonnet class for both checkpoints
**ML Engineer:** comprehension is high-volume/low-stakes, impact is low-volume/high-stakes — tempting to split models. **Quant:** the spec's protection comes from schemas, bounded inputs, and evidence-only prompting, not model size; keep one model, one prompt-engineering surface. **Verdict:** Sonnet-class for both, model string in config, revisit after forward scoring produces evidence either way.

## DR-05.2 — Structured output via tool schema, not "please return JSON"
Define the output as a single tool whose input schema is generated from the Pydantic model (`ComprehensionCard.model_json_schema()`); force `tool_choice`. Malformed output becomes an API-level impossibility rather than a parsing adventure. Validate with Pydantic anyway (defense in depth); on validation error, one retry with the error message appended, then mark the card `failed` for `doctor` to surface.

## DR-05.3 — Cost control by trigger policy, not by model downgrade
Cards are generated only on: (a) new entity that survived 7 days AND has ≥2 evidence types, (b) any maturity promotion, (c) staleness >30 days AND entity is `simmering+`. The 7-day survival gate alone eliminates the majority of one-day-wonder spend.

---

## 1. The contract (`checkpoints/contracts.py`)

```python
class ComprehensionCard(BaseModel):
    entity_ref: str
    what_it_is: str                    # <= 60 words, plain language
    category: CategoryEnum             # must be from the controlled vocabulary
    function: str                      # what it does, mechanically
    claimed_advantage: str             # the pitch, attributed as a claim
    replaces_or_enables: list[str]     # named things/classes it substitutes or unlocks
    maturity_stage: MaturityEnum       # ladder stage per visible evidence
    who_is_behind: str                 # org/individuals, affiliation if visible
    open_questions: list[str]          # what the evidence does NOT establish
    evidence_refs: list[int]           # raw_event ids actually relied on
    confidence: Literal["low","med","high"]
```

`category` from the model is a *proposal*: if it disagrees with the rule-assigned category (doc 04 §5), the disagreement is flagged for review — the model never silently overwrites deterministic state.

## 2. Evidence-pack assembly (deterministic)

`build_evidence_pack(entity_id, as_of) -> str` produces a bounded markdown document, always in the same order:
1. Identity header (names, registries, links, created dates)
2. README / abstract / model card text — **truncated to first 4,000 chars each**
3. Event timeline (compressed: promotions, releases, top HN titles with points)
4. Latest metric snapshot values

Hard cap ~12k tokens. The pack builder is pure and versioned (`pack_version` stored with the card) so cards are reproducible. **Nothing outside the pack reaches the prompt** — no live browsing, no model world-knowledge requests ("use only the evidence provided; write 'not established by evidence' where the pack is silent" is a literal system-prompt line).

## 3. Prompt skeleton (system)

```
You are the comprehension checkpoint of a monitoring system.
Input: an evidence pack about one entity. Output: the card via the tool, nothing else.
Rules:
- Use ONLY the evidence pack. No outside knowledge about this entity.
- Attribute claims: benchmarks and superiority statements are "claims" unless corroborated in-pack.
- If evidence is thin, say so in open_questions and set confidence accordingly.
- what_it_is must be understandable by a non-specialist reader.
```

## 4. Call site mechanics

- `anthropic` SDK, `max_tokens` sized to schema, temperature 0.2.
- `tenacity` retry on 429/5xx (respect `retry-after`), max 3.
- Log per call: entity, model, input/output tokens, cost estimate → `comprehension_cards.cost_usd`; daily spend summed in `doctor` with a hard monthly ceiling env var (`SEISMO_LLM_BUDGET_USD`), calls refuse past the ceiling.
- Batch backfills (initial population, hindcasts) go through the Message Batches API at half price where turnaround doesn't matter.

## 5. Versioning & display

New card = `version + 1`; old versions retained. Dossier view shows latest card with a "changed since v{n-1}" diff of structured fields — comprehension drift is itself information (a project whose `function` changes is pivoting).

## 6. Quality loop

Weekly: sample 10 fresh cards, grade A/B/F on (grounded? attributed? category sane?) in a simple `card_reviews` table. Two consecutive weeks <80% A/B → prompt or pack-builder revision, bump `pack_version`. This is a 15-minute ritual, not a framework.

## 7. Definition of done
- [ ] Contract + enums generated from the shared vocab YAML
- [ ] Pack builder pure, capped, versioned, unit-tested on fixtures
- [ ] Tool-forced call with validation retry; budget ceiling enforced
- [ ] Trigger policy implemented in `seismo comprehend`
- [ ] 50 live cards; 20-card review ≥85% acceptable; median cost ≤ $0.03/card
