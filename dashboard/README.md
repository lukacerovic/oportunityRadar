# Seismograph Dashboard (Stage 5 v0)

Next.js 14 (App Router) + Tailwind. Reads the FastAPI service — never Postgres directly
(doc 10). Dark "Meridian" palette; the momentum 5-colour scale is the one place hue carries
meaning.

## Run

```bash
# 1. API (from repo root)
uv run seismo serve                 # http://127.0.0.1:8000

# 2. Dashboard (this dir)
npm install
npm run dev                         # http://localhost:3000
```

Point the dashboard at a non-default API with `SEISMO_API_BASE` (see `next.config.mjs`).

## Views (v0)

- `/` **Radar** — entities ranked by momentum state → velocity, with a 30-day sparkline and the
  comprehension one-liner. Filter by state.
- `/entity/[id]` **Dossier** — header, KPIs, comprehension card (thesis / open-questions),
  metric trajectory with promotion markers, maturity ladder.
- `/queue` **Merge triage** — two-entity compare, keyboard **M / N / S** (merge / reject / skip).

Briefs, gate audit, and the exposure map are Stage 7–8 additions. In production the TS types in
`lib/types.ts` are generated from the API's OpenAPI schema with `openapi-typescript`.
