# Seismograph — 11 Validation & Hindcast Harness

*Implements idea-spec §9. The harness is not a separate simulator: it is the production pipeline run with historical `as_of` dates over backfilled events. If that sentence is ever untrue, the architecture has failed.*

> **Amended by doc 13:** **A-2** (the harness's as-of purity now genuinely holds only because the *entity graph* is also as-of resolved — the harness must exercise the graph-purity test, not just event visibility); **A-8** (the runner forces `SEISMO_MODEL_HINDCAST`, a pinned snapshot; the 3/3 requirement is what makes that stable); **A-5** (H2's `commercialization` rung is now reachable live via the v1 pricing watcher, not only via the Wayback seed); the **mid-size positive case is resolved as Ollama** (default; asserts the ladder to `distribution` + a non-provisional breakout, not `commercialization`), with Continue.dev as the commercialization-covering alternate — doc 13 Part B. **A-13** (only **H2** needs a real Anthropic call; **H1/H3 are deterministic and free**, and the `mock`/`ollama` providers cover all non-semantic checkpoint testing at $0 — so the hindcast suite is cheap by construction).

---

## DR-11.1 — One codebase, two data origins
**Quant:** a separate "backtest engine" always diverges from production and its results become fiction. **Verdict:** backfill loaders write ordinary `raw_events` rows (`origin='backfill'`, historical `occurred_at`); every analytical function already takes `as_of` (doc 02 §5); hindcasting is therefore just `seismo score --as-of <past-date>` in a loop. The only hindcast-specific code is loaders + assertions.

## DR-11.2 — Cases are pinned as executable assertions
Each case is a YAML file + pytest module, runnable forever (`pytest -m hindcast`). Regressions in thresholds or link rules that would have missed DeepSeek fail CI, not a postmortem.

---

## 1. Historical data acquisition, per source

| Source | Historical route | Notes |
|---|---|---|
| GitHub | **GH Archive** (`gharchive.org` hourly JSON.gz; also BigQuery public dataset) | Loader filters to case-relevant repos/orgs + discovery-query simulation for the window; WatchEvents ≈ star stream → reconstruct `repo_snapshot` counters cumulatively |
| Hacker News | **Algolia API is natively historical** — query by `created_at_i` range | Cheapest, most complete archive we have |
| arXiv | OAI-PMH harvest for window, or Kaggle arXiv metadata snapshot | IDs + dates + comments field survive fine |
| PyPI | BigQuery public dataset `bigquery-public-data.pypi.file_downloads` (free tier ~1 TB/mo query is enough for per-package/day counts) | Only for case packages, not the universe |
| Hugging Face | **No public download history** | Documented gap: reconstruct `usable_artifact` promotions from model `createdAt`; downloads velocity unavailable historically — assertions must not depend on it |
| Pricing pages | Wayback Machine (`archive.org` CDX API) for case entities | e.g., DeepSeek platform pricing page first captures |

Loaders live in `hindcast/loaders/`; each is idempotent and window-scoped. Run once per case into the dev/prod DB (backfill rows coexist safely with live rows — different `occurred_at` eras).

## 2. Case definition format

```yaml
# hindcast/cases/deepseek.yaml
case: deepseek
window: {from: 2024-01-01, to: 2024-07-31}
seeds:                # what loaders must cover
  github: [deepseek-ai]
  arxiv: ["2405.04434"]        # DeepSeek-V2
  hf_orgs: [deepseek-ai]
  wayback: ["platform.deepseek.com"]
assertions:
  - id: H1a
    type: identity
    expect: single_entity(["arxiv:2405.04434","github:deepseek-ai/DeepSeek-V2","hf:deepseek-ai"]) via rules [R1,R2]
  - id: H1b
    type: momentum
    expect: state in [accelerating, breakout] at as_of <= 2024-05-31
  - id: H2
    type: brief
    as_of: 2024-05-31
    expect:
      mechanisms ⊇ [cost_collapse]; mechanisms ∩ [commoditization] != ∅
      exposures include ticker:NVDA and (MSFT or GOOGL or sector_class~"per-token")
      counter_mechanism nonempty; observables nonempty with horizon
```

The brief assertion checks **schema-level facts** (mechanisms, exposure refs, field presence) — never string-matching prose. LLM checkpoints are stochastic; run H2 three times, pass requires 3/3 on mechanisms/exposures. If flaky → the input pack or map slice is underdetermined; fix the pack, not the seed.

## 3. The three v1 cases

1. **DeepSeek (positive, pinned):** as above. The lagging confirmation (Jan 2025 repricing) is deliberately *outside* the window — the system is graded on the foreshock, not the quake.
2. **Mid-size positive (open decision §13 of idea spec):** a developer tool that climbed the full ladder over ~2 quarters (Graphify-type arc). Requirements for a good pick: clean GH Archive trail, a PyPI/npm presence (tests R3 + distribution promotion), a pricing-page appearance (tests commercialization trigger).
3. **Flop negative — Reflection-70B (Sept 2024):** enormous HN/attention spike + HF presence, claims collapsed within days, no distribution, no commitment. Assertions: momentum may briefly reach `simmering` (attention is real) but **gate must suppress** (H3) and **no brief may exist**. This case is what makes cases 1–2 meaningful.

## 4. Runner

```
seismo hindcast --case deepseek [--reload]
```
Steps: (re)load seeds → step daily `as_of` through window running resolve/snapshot/score → run gate weekly → generate H2 brief at pinned `as_of` → evaluate assertions → write `hindcast_runs` row + markdown report (per-day state trace for the case entity — the PMG-demo-grade artifact). `--reload` wipes only that case's backfill rows first (scoped by seeds + window).

## 5. Forward validation (already specified, wired here)

The quarterly calibration report (doc 09 §4) is the *forward* half of this document. The harness contributes its section: all hindcast assertions re-run against current code — the system's permanent regression floor.

## 6. Definition of done
- [ ] Loaders for GH Archive, Algolia-historical, arXiv, Wayback, PyPI-BQ (case-scoped)
- [ ] Case YAML format + assertion evaluators + pytest marker integration
- [ ] DeepSeek case green end-to-end (H1a, H1b, H2 at 3/3)
- [ ] Reflection-70B case green (suppressed, brief-free)
- [ ] Mid-size case selected and green
- [ ] Per-case markdown trace report generated
