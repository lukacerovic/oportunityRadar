# Seismograph — 08 Impact Layer (Exposure Map + LLM Checkpoint 2)

*Implements idea-spec §5 Layer 6, §6, §7. The exposure map is the compounding asset; the checkpoint fills a schema, never free-associates.*

> **Amended by doc 13:** **A-1** (the YAML schema + loader + `reach_links` derivation + a minimal 8-company slice are built at the *start of Stage 6*, before the gate; only the full 30-company curation stays here in Stage 7 — the final roster is fixed in doc 13 Part B); **A-7** (`observables` becomes `list[Observable]` with a `source: system|manual` measurability tag; prefer machine-measurable falsifiers); **A-8** (model from `SEISMO_MODEL_LIVE`; hindcast pins `SEISMO_MODEL_HINDCAST`); **A-12** (budget-ceiling → brief request stays `pending`; the gate never briefs an entity whose comprehension card is `pending`).

---

## DR-08.1 — Exposure map as YAML-in-git, loaded into Postgres
**Data Engineer:** hand-curated, slowly-changing, review-worthy data belongs in version control — diffs are the maintenance log, git blame is the provenance. A DB-edited map has neither. **Frontend:** editing YAML is worse UX than a form. **Verdict:** YAML in `exposure_map/` is the source of truth; `seismo load-map` validates (Pydantic) and upserts into `exposure_companies` + `reach_links`; the dashboard *renders* the map but v1 does not edit it. *Revisit trigger: map curation exceeds ~1 h/week — then build the form that writes YAML via PR.*

## DR-08.2 — Human review mandatory before publish (v1)
Briefs are generated as `draft`. The operator reviews in the dashboard and publishes or rejects with a reason. Auto-publish is earned, not assumed: enabled only after two quarters of forward scoring show acceptable calibration (doc 09). No dissent.

## DR-08.3 — Revenue lines grounded in EDGAR, refreshed quarterly
`https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` (free, declared User-Agent, ≤10 req/s) provides reported revenue facts; segment detail beyond XBRL granularity is completed by hand from 10-K segment notes during the quarterly refresh. The YAML records the figure, period, and source URL for every revenue line — auditable per idea-spec §6.

---

## 1. Company YAML schema

```yaml
# exposure_map/NVDA.yaml
ticker: NVDA
name: NVIDIA Corporation
cik: "0001045810"
sector: semiconductors
revenue_lines:
  - id: datacenter
    name: Data Center
    share_of_revenue: 0.87        # latest FY, from companyfacts + 10-K segment note
    source: "10-K FY2025, segment note; companyfacts rev facts"
    depends_on: [frontier-training-demand, inference-demand, cuda-moat]
    threat_surface:
      - category: model-efficiency
        relation: demand_risk      # cheaper training/inference → fewer GPUs per capability unit
        core: true
      - category: inference-runtime
        relation: substitution_partial
moat_notes: >
  CUDA ecosystem lock-in; networking (NVLink) attach; supply relationships.
sensitivity_notes: >
  Exposed to any credible collapse in training-compute-per-capability; watch
  efficiency papers that replicate at scale, not just claim.
updated: 2026-07-01
```

Pydantic loader enforces: shares sum ≤1.05, every `threat_surface.category` exists in the category vocabulary, every line has a `source`. `reach_links` rows are derived from `threat_surface` entries at load time — the gate (doc 07) and this layer read the same curated linkage.

**v1 roster (~30, final list = open decision):** NVDA AMD TSM AVGO ASML · MSFT AMZN GOOGL META AAPL ORCL · CRM ADBE NOW TEAM WDAY INTU · SNOW MDB DDOG NET CFLT · PLTR SHOP U DOCN · plus per-theme picks. Budget the curation honestly: ~45 min per company first pass; it is Stage 7's long pole and it is worth it.

**Private companies:** never get YAML files. They exist as entities and inside transmission chains; the checkpoint's schema (below) forces exposure resolution to tickers or `sector_class` strings ("per-token API revenue models"). This implements idea-spec §6 verbatim.

## 2. The contract (`checkpoints/contracts.py`)

```python
class TransmissionStep(BaseModel):
    from_node: str; to_node: str; effect: str          # explicit path, 2–5 steps

class Observable(BaseModel):                            # A-7: structured + measurability-tagged
    statement: str                                      # "avg tokens per active customer falls"
    source: Literal["system","manual"]                  # can the pipeline watch this?
    system_metric: str | None                           # if source=system: metric/event it maps to
    horizon: Literal["quarters","1-2y","3y+"]
    direction_if_thesis_holds: Literal["up","down","flat"]

class Exposure(BaseModel):
    kind: Literal["ticker","sector_class"]
    ref: str                                           # "NVDA" or class string
    revenue_line: str | None                           # must exist in map when kind=ticker
    direction: Literal["negative","positive","ambiguous"]
    magnitude_class: Literal["marginal","material","structural"]

class ImpactBrief(BaseModel):
    entity_ref: str
    mechanisms: list[MechanismEnum]                    # substitution|cost_collapse|commoditization|enablement|dependency_risk
    transmission_path: list[TransmissionStep]
    exposures: list[Exposure]
    counter_mechanism: str                             # REQUIRED, stated fairly
    observables: list[Observable]                      # A-7: ≥1 required; prefer source="system"
    confidence: Literal["low","med","high"]
    horizon: Literal["quarters","1-2y","3y+"]
    summary: str                                       # <= 200 words, readable
    evidence_refs: list[int]
```

Post-validation (code, not model): every ticker exposure's `revenue_line` must exist in the loaded map; every mechanism must be legal for the relation types in the touched `threat_surface`; reject otherwise with one schema-error retry, then `failed`.

## 3. Input pack (deterministic, versioned like doc 05 §2)

1. Latest comprehension card (structured fields)
2. Momentum summary: state history, promotions, velocity percentiles
3. **Map slices only** — the YAML of companies whose `reach_links` matched this entity's category, truncated to relevant revenue lines. The model never sees the whole map; it reasons over pre-selected surface.
4. Mechanism taxonomy definitions (verbatim from idea-spec §7)

System prompt adds: *"You explain exposure; you never predict prices. State the strongest counter-mechanism as convincingly as its holder would. If the honest direction is ambiguous, say ambiguous — that is a finding, not a failure."*

## 4. Workflow

`seismo brief --entity-id N` (fed by the gate queue) → draft row → dashboard review page renders schema fields + evidence links → operator publishes / rejects-with-reason. Published briefs are immutable; updates create version+1 (triggered by re-gating, doc 07 §1). Rejections keep the draft + reason — they feed the same quality loop as doc 05 §6.

## 5. Quarterly map refresh (calendar ritual, ~2–3 h)

Earnings season trigger per name: pull fresh companyfacts, re-check segment shares against the new 10-K/10-Q, update `share_of_revenue` + `updated`, git commit per company. `seismo doctor` warns on any YAML older than 120 days (guards idea-spec failure mode #5).

## 6. Definition of done
- [ ] YAML schema + validating loader + `reach_links` derivation
- [ ] 30 companies curated with sourced revenue lines
- [ ] EDGAR fetcher with UA + rate ceiling
- [ ] Brief contract + post-validation + review workflow end-to-end
- [ ] **H2 passes:** DeepSeek brief from ≤2024-05-31 data names cost_collapse + commoditization, NVDA/MSFT/GOOGL-class exposures, a real counter-mechanism, and dated observables
