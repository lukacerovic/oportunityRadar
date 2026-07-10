# Seismograph — 10 Dashboard (The Four Views)

*Implements idea-spec §3. One web app, four projections of the same knowledge, plus the three curation surfaces (merge queue, brief review, scoring).*

> **Amended by doc 13:** **A-10** (add `GET /search?q=&type=` to the API surface in Stage 5 so the contract is stable; a header search box + results list is a Stage 8 UI add); **A-6** (the `/gate/[week]` page shows the `unmapped_reach` suppressions and the map-gaps list); **A-7** (the brief view renders each observable's `source` tag — `system` vs `manual` — and the `/review` scoring screen shows auto-evaluated system observables). The `/queue` page gains the cold-start precision-first mode (doc 14 §8).

---

## DR-10.1 — Next.js + FastAPI over FastAPI + Jinja/htmx
**Ops Minimalist (htmx case):** one process, no Node on the server, server-rendered — genuinely sufficient for a read-mostly tool. **Frontend (Next case):** Radar and Dossier want client-side interactivity (filtering hundreds of entities, sparkline hover, keyboard-driven queue triage); the React charting ecosystem is decisively better; and the operator already works in Next.js daily — familiarity is a real engineering input. **Verdict:** Next.js 14+ App Router, TypeScript, Tailwind, Recharts, talking JSON to FastAPI. The htmx path is recorded as the legitimate road-not-taken. *Revisit trigger: none expected.*

## DR-10.2 — Auth: Caddy basic_auth (v1)
Single user, personal infra. Caddy `basic_auth` over HTTPS in front of both apps; FastAPI additionally requires a static bearer token (belt and suspenders, and it keeps the API honest if it's ever exposed separately). No user tables, no sessions, no OAuth. Multi-user is explicitly deferred (idea-spec §10).

## DR-10.3 — Data fetching: server components + 5-minute cache
Data changes once a day; interactivity is client-side over already-fetched JSON. Server components fetch from FastAPI on request with short revalidation. No websockets, no polling, no state library beyond React state + URL params.

---

## 1. FastAPI surface (`api/`)

Read endpoints (all accept `as_of` for time-travel debugging):
```
GET /radar?theme=&state=            → entities w/ state, sparkline data, card one-liner
GET /entities/{id}                  → dossier: card versions, timeline, metrics, promotions, briefs
GET /changes?date=                  → rendered changes_daily
GET /briefs?status=                 → list; GET /briefs/{id} → full schema + evidence
GET /gate/{week}                    → passed + suppressed with components
GET /themes                         → rollups
GET /map / /map/{ticker}            → rendered exposure map
GET /health                         → doctor summary for the header status dot
```
Curation endpoints (bearer-token, non-GET):
```
POST /merge-queue/{id}/decision     {merge|reject|skip}
POST /briefs/{id}/review            {publish|reject, reason}
POST /briefs/{id}/score             brief_scores payload
POST /entities/{id}/themes          override assignment
```
Pydantic response models throughout; OpenAPI schema → generate the TS client (`openapi-typescript`) so the two codebases can't drift silently.

## 2. Pages and components (`dashboard/app/`)

| Route | View | Key components |
|---|---|---|
| `/` | **Radar** | ThemeGrid → EntityCard (name, state chip, 30d sparkline, card one-liner); filters: theme, state, category; sort: state → velocity pctl |
| `/entity/[id]` | **Dossier** | Header (registries, stage ladder progress), MetricChart (Recharts line, promotions as reference dots), EventTimeline (virtualized), CardPanel w/ version diff, BriefList |
| `/changes` | **Changes** | Date-keyed sections per §1 of doc 09; Monday = week mode |
| `/briefs` + `/briefs/[id]` | **Impact** | Schema-rendered brief: mechanism chips, TransmissionPath (simple SVG step list — no graph lib), ExposureTable w/ links into `/map/[ticker]`, counter-mechanism callout (visually co-equal with the thesis — design encodes epistemics), observables checklist |
| `/queue` | Merge triage | Two-entity compare, evidence snippet, **keyboard: M / N / S** — throughput is the feature |
| `/review` | Brief review + scoring | Draft queue; quarterly scoring mode per doc 09 §2 |
| `/gate/[week]` | Gate audit | Passed + suppressed tables w/ component bars |
| `/map` | Exposure map | Company cards → revenue lines w/ threat-surface chips, staleness badge |

Design intent: dense, quiet, text-first — a terminal for reading the frontier, not a marketing dashboard. States get a fixed 5-color scale used *nowhere else*, so color always means momentum.

## 3. Build & deploy shape

`next build` → run with `next start` under systemd (Node LTS via apt/nodesource) behind Caddy at `/`; FastAPI (uvicorn, systemd) behind Caddy at `/api/*`. Dashboard never touches Postgres directly — the API is the only door, which is also what keeps `as_of` semantics in one place. (Static export was considered and rejected: server components + revalidation are worth one Node process.)

## 4. Definition of done
- [ ] TS client generated from OpenAPI; CI regenerates and diffs
- [ ] Radar + Dossier + Changes render live data (Stage 5 = these three read-only + `/queue`)
- [ ] Brief review/scoring + gate audit + map (Stage 7–8 additions)
- [ ] Keyboard triage on `/queue` measured: 20 items < 10 minutes
- [ ] Morning-coffee test (build plan Stage 5 exit) passes 3 consecutive days
