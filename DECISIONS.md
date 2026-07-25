# Decisions

Running log of source/metric decisions that don't belong in code comments or the
design docs. One entry per decision, newest first.

## 2026-07-24 — OpenRouter reversal: leaderboard usage + model-list correlation

User decision overriding yesterday's no-go, with a narrower scope than the original
plan. What ships:

- **`openrouter` collector** (discover-only, keyless, daily in the `all` group).
  `or_model_listed` events for models newly listed on OpenRouter (window on the
  `created` timestamp); `or_rankings` events for the weekly top-10 token
  leaderboards (`tools`/`images` categories).
- **Correlation is the point:** an OpenRouter event anchors to the *model's
  existing entity* — via `hugging_face_id` onto the HF entity when weights are
  public, else via display name onto the `web` product anchor an HN launch mints
  ("MoonshotAI: Kimi K3" → `web:kimi-k3`). No new registry. So "Kimi K3 tokens are
  moving this week" lands as usage evidence on the same entity as its HN attention
  and shows in the dossier ("OpenRouter rankings") and in `evidence_breadth`.
- **`or_tokens_wk`** metric: level, `evidence_type="usage"`, composite — joins the
  adoption leg of `hype_gap` by construction (evidence-type-derived groups).

Accepted limitations, on the record: coverage is top-10-per-category only (a
watchlist long-tail model will simply have no rows — absent metrics are a no-op);
the rankings endpoint is unofficial and has churned once already, so its fetch is
best-effort per category and a dead category degrades to model-listing evidence
only. The official `/api/v1/models` list is the stable half of the pair.

## 2026-07-23 — Phase 0 verdicts: market-source expansion spike

Live-probed three candidate keyless sources for new weekly metrics. Raw payloads
recorded under `tests/fixtures/{source}/`. Per the plan, no-go sources are dropped,
not worked around.

### Substack — **GO**

Curated-feed RSS works exactly as hoped: `{pub}` feeds (`interconnects.ai/feed`,
`importai.substack.com/feed`, `garymarcus.substack.com/feed`) all returned 200 and
parse cleanly with stdlib `xml.etree` (fixture: `substack/interconnects_feed.xml`,
trimmed to 3 items). Alias matching against titles+descriptions is signal, not
noise: probe hits were all genuine ("Claude Fable 5 and …" → claude, "… Gemma 4,
De[epSeek]" → deepseek, "Kimi K3, Qwen 3.8" → qwen), zero false positives across
60 items × 10 aliases. Feeds are shallow (20 items) but ample at 24h cadence.
Metric: `substack_mentions`, rolling 7d count, `evidence_type="attention"`.
Curated feed list lives in config.

### OpenRouter — **NO-GO** (by the plan's own criterion)

The official keyless API (`/api/v1/models`, 200) carries pricing/context/params for
343 models but **zero usage data**. Per-model token charts on model pages load
client-side and no per-model stats endpoint is publicly reachable (model page HTML
contains no usage numbers; the historical `api/frontend/models*` paths are dead —
404). What does exist is `api/frontend/v1/rankings/{tools,images}` (fixture:
`openrouter/rankings_tools.json`): weekly top-10 token leaderboards, 13 data
points over ~3 months, 28 distinct models, only two niche categories, unofficial
path that has already churned once. That is a leaderboard, not per-entity coverage
for a watchlist — using it would be a workaround, and the plan says drop, don't
work around. Revisit if OpenRouter ships an official usage endpoint.

### Reddit — **NO-GO keyless** (keyed OAuth is a possible future decision)

Keyless JSON is hard-blocked: `search.json` returns 403 (bot-wall HTML) across
`www.`/`old.`/`api.` hosts and all User-Agents tried, from the first request. RSS
(`search.rss`) does respond 200 (fixture: `reddit/search_new_rss.xml`) but is
unusable for `reddit_heat` as specced: entries carry **no scores**, and the
`t=week`/`sort=new` filters are ignored (a 2025-03 post appeared under `t=week`).
Rate limiting escalated to 429 after ~8 requests in two minutes — a 50-alias × 6h
poll is not viable. The sum-of-scores metric therefore cannot be built keylessly.
Alternative if wanted later: free Reddit OAuth app (scores available, 100 QPM),
which would fit the existing optional-token pattern (`github_token`/`hf_token` in
`config.py`) — but that is a new decision (first keyed-by-necessity source), not a
Phase 2 as planned.

**Consequence:** the expansion collapses to one new source (Substack). Phase 1
becomes the Substack collector; original Phases 1–2 (OpenRouter, Reddit) are
dropped.
