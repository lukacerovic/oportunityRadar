# Seismograph — 03 Observation Layer (Collectors)

*Implements idea-spec §5 Layer 1. Collectors record what happened; they never interpret. Output: rows in `raw_events`.*

> **Amended by doc 13:** **A-4** (`track()` polls only `active`-tier entities daily / `slow`-tier weekly; archived entities are skipped and revived on any new inbound event — the tracking set is bounded, not monotonic); **A-5** (the **pricing/changelog watcher §2.8 is promoted from Wave 3 into v1** as a weekly sub-cadence of `collect-usage`, restoring the `commercialization` evidence type and ladder rung; jobs stays Wave 3); **A-9** (arXiv categories extend to `cs.AI, cs.CL, cs.LG, cs.SE, cs.IR, stat.ML, cs.CR, cs.MA, cs.CV, cs.DC`, kept in config); **A-11** (`source_event_uid` snapshot date and all `day` keys use the **UTC calendar date of `occurred_at`**). Cold-start historical discovery sweep: doc 14 §4.

---

## DR-03.1 — Scheduling: systemd timers over APScheduler over Airflow
**Ops Minimalist:** a daily batch needs cron semantics, process isolation, and logs — systemd timers give all three natively, and a hung collector can't take the API server down with it. **Pipeline advocate for APScheduler:** one process, easier local dev. **Everyone on Airflow/Dagster/Prefect:** operational weight vastly exceeds value for ~8 jobs/day. **Verdict:** systemd timers → `seismo collect --source X`; local dev just runs the CLI manually. *Revisit trigger: if intra-day cadence or DAG complexity ever appears.*

## DR-03.2 — Wave 1 sources: GitHub + Hacker News + arXiv
Chosen because together they cover participation + attention + capability claims, all three have excellent historical archives (critical for hindcast), and all three are free. HF + PyPI/npm follow in Wave 2 (usage evidence). Reddit, jobs, pricing watchers are Wave 3. X/Twitter is out of v1 entirely (API cost, low marginal signal over HN).

## DR-03.3 — Discovery vs tracking split
Every collector runs in two modes. **Discovery** finds new candidate entities (broad queries, topic filters). **Tracking** deep-polls entities we already know (their repos, models, packages). This keeps API budgets sane: broad-and-shallow for the unknown, narrow-and-deep for the known.

---

## 1. Collector contract

```python
class RawEventDraft(BaseModel):
    source: str; source_event_uid: str; event_type: str
    occurred_at: datetime; payload: dict

class BaseCollector(Protocol):
    source: str
    def discover(self, window: Window) -> list[RawEventDraft]: ...
    def track(self, targets: list[TrackTarget], window: Window) -> list[RawEventDraft]: ...
```

Framework responsibilities (shared code, not per-collector): insert with `ON CONFLICT (source, source_event_uid) DO NOTHING`, write `collector_runs` row, retry with `tenacity` (exp backoff, max 3), respect per-source rate limiter, tag `origin='live'`.

Collector responsibilities: fetch, normalize timestamps to UTC, choose a stable `source_event_uid`, dump the *full* raw payload into `payload`. Nothing else. If a collector contains an `if` about meaning, it is wrong.

**Snapshot-type events.** Metrics like star counts are states, not events. Convention: `event_type='*_snapshot'`, `source_event_uid = f"{native_id}:{date}"`, one per target per day. The trajectory layer turns snapshots into deltas.

## 2. Source-by-source implementation

### 2.1 GitHub
- **Auth/limits:** PAT; REST 5,000 req/h; Search API 30 req/min — the real constraint.
- **Discovery:** Search API, daily: `created:>=<yesterday>` intersected with topic/keyword lists per theme (e.g. `topic:llm`, `topic:agents`, keyword sets from doc 04 §5); plus `pushed:>=<yesterday> stars:>50` for late discovery of risers. Record `repo_discovered` events with full repo object.
- **Tracking:** for tracked repos: daily `repo_snapshot` (stars, forks, subscribers, open_issues), `release_published` (from /releases), contributor count monthly (expensive endpoint — sample).
- **Payload keys that matter later:** `html_url`, `homepage`, `description`, `topics`, `owner.login`, README fetch (separate `readme_snapshot` weekly — identity layer mines it for arXiv/HF/PyPI links).
- **Library:** raw `httpx` + minimal client. PyGithub adds little.

### 2.2 Hacker News (Algolia Search API)
- **Endpoint:** `https://hn.algolia.com/api/v1/search_by_date?tags=story&numericFilters=created_at_i>...` — free, no key, and **fully historical**, which makes it the hindcast workhorse.
- **Discovery:** all stories in window matching theme keyword lists OR any story with `points > 50` linking to github.com / arxiv.org / huggingface.co — URL-based capture is higher precision than keywords.
- **Tracking:** re-poll story points/comments at +24h and +72h (`story_snapshot`) to measure attention decay.
- **Payload:** `objectID` (uid), `url`, `title`, `points`, `num_comments`, `created_at_i`.

### 2.3 arXiv
- **Endpoint:** export API (Atom), categories `cs.AI, cs.CL, cs.LG, cs.SE, cs.IR, stat.ML`; politeness ~1 request / 3 s, paginate 100/page.
- **Discovery:** daily new submissions in categories → `paper_published` with full metadata (id, title, abstract, authors, comments field — often contains the GitHub link, gold for identity).
- **Tracking:** v1 skips citation velocity (Semantic Scholar API is the Wave-3 add for `citation_snapshot`).
- **Bulk/hindcast:** OAI-PMH harvesting or the Kaggle arXiv metadata snapshot (doc 11 §2).

### 2.4 Hugging Face (Wave 2)
- **Library:** `huggingface_hub.HfApi().list_models(...)` with `sort="lastModified"`, filters by pipeline tags.
- **Discovery:** models/datasets created in window; **Tracking:** daily `model_snapshot` (downloads, likes). 
- **Measurement caveat (recorded in payload contract):** `downloads` is a ~30-day rolling figure, not cumulative — trajectory layer must treat it as a level, not a counter.
- **Identity gold:** model card metadata frequently contains `arxiv:` IDs and GitHub links.

### 2.5 PyPI / npm (Wave 2)
- **PyPI:** discovery of *new relevant* packages via the RSS of newest packages is noisy; better: for every tracked GitHub repo, check `pyproject/setup` name and query **pypistats.org** API (`/api/packages/{pkg}/recent`) daily → `pkg_downloads_snapshot`. Distribution evidence is mostly a *tracking* signal, not discovery.
- **npm:** registry + `api.npmjs.org/downloads/point/last-week/{pkg}` same pattern.
- **Identity gold:** PyPI JSON (`/pypi/{pkg}/json`) `project_urls` → GitHub link (deterministic R-rule, doc 04).

### 2.6 Reddit (Wave 3)
PRAW with OAuth (script app), subreddits: MachineLearning, LocalLLaMA, artificial, programming, devtools. Daily top+new in window, same URL-capture heuristic as HN. Free tier (~100 QPM) is ample. Attention evidence only.

### 2.7 Jobs (Wave 3)
- **HN "Who is hiring"** monthly threads via Algolia (`tags=ask_hn`, title match) → parse comments for tracked-entity mentions → `job_mention` events. Legal, structured, monthly cadence.
- **Greenhouse/Lever public JSON** (`boards-api.greenhouse.io/v1/boards/{org}/jobs`) for exposure-map companies → counts of postings mentioning tracked techs → commitment evidence.
- LinkedIn scraping: **rejected** (ToS, fragility).

### 2.8 Pricing & changelog watcher (Wave 3)
For entities at maturity ≥ `usable_artifact`: known URLs (pricing, changelog, blog) fetched weekly with `httpx`, text extracted with `trafilatura`, content-hashed; on change → `page_changed` event with old/new hash + extracted text. Respect robots.txt; per-domain 1 req/min ceiling. First appearance of a pricing page is the `commercialization` promotion trigger (doc 06).

## 3. Scheduling matrix (systemd timers, doc 12 has units)

| Timer | Runs | Sources |
|---|---|---|
| `seismo-collect-fast` | daily 05:30 UTC | github, hn, arxiv |
| `seismo-collect-usage` | daily 05:50 UTC | hf, pypi, npm |
| `seismo-collect-slow` | weekly / monthly | reddit, jobs, pricing |
| `seismo-pipeline` | daily 06:15 UTC | resolve → snapshot → score → comprehend (order fixed) |

## 4. Politeness & resilience rules
1. One shared `RateLimiter` per source (token bucket), limits configured, honored even in backfills.
2. Descriptive User-Agent with contact email on every non-authenticated source (arXiv and EDGAR require it in spirit and letter).
3. Any collector failure is isolated: logged, `collector_runs.ok=false`, run continues with other sources. Silence-detection lives in `seismo doctor` (doc 12): alert if a source has 0 new events for N× its normal cadence.
4. Never parse HTML where an API exists; never scrape a source that forbids it — the system's legitimacy is part of its design.

## 5. Definition of done (per collector)
- [ ] Discovery + tracking implemented against contract; UTC timestamps; stable uids
- [ ] Re-run of same window inserts 0 rows (idempotence test)
- [ ] Rate limiter + retries wired; failure isolation verified by killing it mid-run
- [ ] 7 green daily runs in `collector_runs`
- [ ] Payload contract documented in module docstring (what keys downstream layers may rely on)
