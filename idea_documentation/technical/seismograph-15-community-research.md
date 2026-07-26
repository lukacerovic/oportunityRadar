# Seismograph - 15 Community Research Layer

*Adds a refreshable community-opinion layer for already-collected entities. v1 target: Reddit only. Discord and other communities are explicitly deferred.*

---

## 0. Intent

The product already collects projects, papers, models, and launches from sources such as GitHub, Hacker News, arXiv, and Hugging Face. This feature answers a separate question:

> "What does the public community say about this thing?"

For each existing entity, the system should search Reddit for meaningful public discussion, summarize the discussion, link to relevant threads, and clearly report when no discussion was found.

This is **not** a new discovery source in v1. Reddit should not create new entities. It should enrich entities that already exist in the knowledge graph.

---

## DR-15.1 - Enrichment job, not live lookup

**Verdict:** community research runs as a background enrichment job, not inside `GET /entities/{id}`.

Reasons:

- Reddit search and comment fetches are network-bound and rate-limited.
- The dashboard must stay fast and deterministic.
- Summaries should be cached, auditable, and refreshable.
- Failed Reddit calls should not break project pages.
- The same result can be reused until the entity is due for refresh.

The API only reads stored community research rows.

---

## DR-15.2 - Reddit-only v1

**Verdict:** implement Reddit first. Defer Discord.

Reddit has public permalinked discussions, search surfaces, scores, comment counts, timestamps, and subreddit context. That makes it suitable for repeatable enrichment.

Discord is different:

- no reliable global public search;
- server access is permission-based;
- bots must be installed per server;
- many conversations are private or semi-private;
- links are less useful unless the reader has server access.

Discord can become a later per-community integration, not part of this first layer.

---

## DR-15.3 - Do not ingest Reddit as `raw_events` by default

Reddit discussion summaries are derived analysis over existing entities, closer to `comprehension_cards` and `impact_briefs` than to immutable primary observations.

Use a dedicated table:

```sql
CREATE TABLE entity_community_research (
  id BIGSERIAL PRIMARY KEY,
  entity_id BIGINT NOT NULL REFERENCES entities(id),
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  query_set JSONB NOT NULL,
  result JSONB NOT NULL,
  model TEXT,
  researched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_entity_community_research_entity_source
  ON entity_community_research (entity_id, source, researched_at DESC);

CREATE INDEX ix_entity_community_research_status
  ON entity_community_research (status);
```

`source` is `reddit` for v1.

`status` values:

- `found` - relevant public discussion was found and summarized.
- `not_found` - search ran successfully, but no relevant discussion passed filters.
- `failed` - Reddit/API/summarization failed; retry later.
- `pending` - selected for research but not completed yet. Optional for queue-style implementations.

Keep the newest row as the active result. Do not update old rows in place unless storage becomes a problem. Append-only rows make it possible to inspect how community discussion changed over time.

---

## 1. User-facing behavior

On the entity dossier page, add a "Community" or "Community discussion" section.

When discussions are found:

```text
Reddit discussion found

Summary:
Community reaction is mixed-positive. Users are interested in the project because of its benchmark results and simple API, but several comments question reproducibility and long-term maintenance.

Main points:
- Users compare it with ...
- The strongest positive signal is ...
- The main concern is ...

Threads:
- r/MachineLearning - "..." - 183 points - 47 comments
- r/LocalLLaMA - "..." - 92 points - 31 comments

Last checked: 2026-07-24
```

When no relevant discussion is found:

```text
No public Reddit discussion found

We could not find meaningful public Reddit discussion about this project yet.

Last checked: 2026-07-24
```

When research failed:

```text
Community research unavailable

The last Reddit research attempt failed. The system will retry on a later run.
```

The UI should always show thread links for reader verification. Never show only the model summary.

---

## 2. Daily pipeline placement

Community research should run after entities are resolved and after enrichment has produced better names/descriptions.

Recommended daily order:

```bash
seismo collect --source fast --window 1d
seismo resolve
seismo track --source github
seismo enrich-readmes --missing --limit 100
seismo enrich-hn --limit 100
seismo enrich-hf --limit 100
seismo comprehend
seismo score
seismo community-research --source reddit --limit 200
```

It can also run before `score`; it does not need trajectory output. However, running after `comprehend` is useful because the latest card gives better context for query generation and relevance filtering.

This job should be independently rerunnable and idempotent enough for daily operations.

---

## 3. Refresh policy

Do not search every entity every day. Select a bounded due set.

Suggested v1 policy:

| Entity condition | Refresh cadence |
|---|---:|
| No community row exists | now |
| `breakout` or `accelerating` | every 24 hours |
| `simmering` | every 3 days |
| `fading` or `dormant` | every 7-14 days |
| Last status `not_found` | every 7 days |
| Last status `failed` | retry after 24 hours |
| `tracking_tier = archived` | skip |

The CLI `--limit` caps the selected due set so Reddit budget is predictable.

Selection query should prioritize:

1. entities with no community result;
2. high-momentum entities;
3. recent entities;
4. stale `not_found` rows;
5. stale successful rows.

---

## 4. Target selection

Create a selector similar to existing enrichment target selectors.

Proposed function:

```python
def select_community_targets(
    session: Session,
    source: str,
    *,
    limit: int | None = None,
    as_of: datetime,
) -> list[CommunityTarget]:
    ...
```

Target shape:

```python
@dataclass(frozen=True)
class CommunityTarget:
    entity_id: int
    canonical_name: str
    entity_type: str
    category: str | None
    anchors: dict[str, str]
    owner: str | None
    description: str | None
    card: dict[str, Any] | None
    state: str
    last_researched_at: datetime | None
    last_status: str | None
```

Relevant entity fields:

- `entities.canonical_name`
- `entities.entity_type`
- `entities.category`
- `entities.attrs->'anchors'`
- `entities.attrs->>'owner'` if present
- latest `comprehension_cards.card`
- latest `momentum_states.state`
- latest `entity_community_research` row

Skip merged entities and archived entities.

---

## 5. Query generation

The most important part of this feature is relevance. Many project names are ambiguous.

Generate several candidate queries per entity, ordered from precise to broad:

### GitHub-backed entity

Inputs:

- `anchors.github`, usually `owner/repo`
- canonical name
- repo homepage if available in attrs or evidence
- README/card description

Queries:

```text
"owner/repo"
"repo-name" "owner"
"repo-name" github
"canonical name" github
"canonical name" "what it is keyword"
```

### arXiv-backed entity

Inputs:

- paper title
- arXiv id
- authors if available
- project/repo link if extracted from paper metadata

Queries:

```text
"exact paper title"
"arXiv:2501.12345"
"paper title key phrase" "first author"
```

### Hugging Face-backed entity

Inputs:

- model id, usually `org/model`
- model name
- task/pipeline tag

Queries:

```text
"org/model"
"model-name" "Hugging Face"
"model-name" "LLM"
```

### HN/web launch-backed entity

Inputs:

- canonical name
- launch URL/domain
- HN title
- card description

Queries:

```text
"canonical name"
"domain.com"
"canonical name" "product keyword"
```

### Query limits

Keep v1 to roughly 3-6 queries per entity. More queries increase cost and false positives.

Store the exact query set in `entity_community_research.query_set`.

---

## 6. Reddit access

Use official Reddit API access, preferably through PRAW or a small `httpx` client.

Required configuration:

```env
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=OpportunityRadar/0.1 by u/<reddit_username>
```

Do not hardcode credentials.

### API/cost note

Reddit API access is not "free for anything." Reddit offers free and paid access, but production/commercial use can require approval or a paid agreement. Before shipping this in a commercial product, confirm the current Reddit Data API Terms and developer policies.

Engineering assumption for v1: build the integration so it can be disabled by missing credentials and so daily volume is capped.

---

## 7. Search strategy

Preferred v1 implementation:

1. Search Reddit submissions for each generated query.
2. Keep recent and historically relevant matches.
3. Fetch comments only for top relevant submissions.
4. Summarize bounded snippets.

Potential search surfaces:

- Reddit API search via subreddit/global search if available under account access.
- PRAW submission search.
- Fallback: use Reddit's public search only if compliant and stable enough. Avoid scraping pages.

Configurable subreddit allowlist can improve precision:

```python
REDDIT_SUBREDDITS = [
    "MachineLearning",
    "LocalLLaMA",
    "artificial",
    "singularity",
    "programming",
    "opensource",
    "selfhosted",
    "webdev",
    "datascience",
]
```

But do not search only allowlisted subreddits. Some projects are discussed in niche communities. v1 should support:

- global search;
- optional subreddit allowlist boost;
- optional subreddit blocklist for noisy/off-topic places.

---

## 8. Relevance scoring

Reddit search results will contain false positives. Add a deterministic relevance score before summarization.

Suggested scoring inputs:

- exact `owner/repo` match in title/body/comments;
- exact URL/domain match;
- exact canonical name match;
- arXiv id match;
- model id match;
- subreddit topicality;
- result score and comment count;
- date recency;
- negative penalty for unrelated contexts.

Example:

```python
score = 0
if exact_anchor_match:
    score += 60
if exact_name_match:
    score += 25
if domain_match:
    score += 30
if subreddit in trusted_subreddits:
    score += 10
if comments_count >= 10:
    score += 5
if reddit_score >= 50:
    score += 5
if ambiguous_name_without_anchor:
    score -= 40
```

Threshold guidance:

- `>= 60`: relevant, fetch comments.
- `40-59`: maybe relevant; include only if there are few better results.
- `< 40`: discard.

For ambiguous names, require an anchor match or supporting context. Example: a project named "Crew" or "Pilot" should not match generic Reddit posts unless GitHub owner, URL, domain, or exact technical context is present.

---

## 9. Comment fetching and bounds

For each relevant submission:

- fetch title, selftext, URL, subreddit, score, comment count, created timestamp, permalink;
- fetch top comments by Reddit ranking;
- cap to top 20-50 comments total per entity;
- cap text by characters/tokens before LLM summarization;
- exclude deleted/removed comments;
- keep enough comment metadata for audit.

Suggested bounds:

```python
MAX_THREADS_PER_ENTITY = 5
MAX_COMMENTS_PER_THREAD = 20
MAX_TOTAL_COMMENT_CHARS = 30000
```

Avoid storing full unbounded Reddit comment trees. Store only the subset used to produce the summary, plus permalinks to source threads.

---

## 10. Summary schema

Store structured JSON in `result`.

When found:

```json
{
  "status": "found",
  "summary": "Community reaction is mixed-positive...",
  "sentiment": "mixed_positive",
  "confidence": "medium",
  "main_points": [
    "Users like ...",
    "Several comments question ...",
    "The most discussed use case is ..."
  ],
  "concerns": [
    "Reproducibility is unclear",
    "Maintenance risk"
  ],
  "positive_signals": [
    "Practitioners report trying it",
    "Comparison with established tools is favorable"
  ],
  "threads": [
    {
      "reddit_id": "abc123",
      "title": "...",
      "subreddit": "MachineLearning",
      "url": "https://www.reddit.com/r/MachineLearning/comments/...",
      "score": 183,
      "comment_count": 47,
      "created_at": "2026-07-20T10:15:00Z",
      "relevance_score": 82,
      "matched_queries": ["\"owner/repo\""]
    }
  ],
  "searched_queries": ["..."],
  "notes": []
}
```

When not found:

```json
{
  "status": "not_found",
  "summary": "We could not find meaningful public Reddit discussion about this project yet.",
  "sentiment": null,
  "confidence": "high",
  "main_points": [],
  "concerns": [],
  "positive_signals": [],
  "threads": [],
  "searched_queries": ["..."],
  "notes": ["No result passed relevance threshold."]
}
```

When failed:

```json
{
  "status": "failed",
  "summary": "Community research failed and will be retried later.",
  "error": "RateLimitError: ...",
  "threads": [],
  "searched_queries": ["..."]
}
```

---

## 11. Summarization rules

The summarizer must ground every claim in the fetched Reddit threads. It should not use outside knowledge.

Prompt rules:

- summarize only the provided Reddit content;
- distinguish positive, negative, mixed, and neutral reactions;
- report uncertainty when discussion is thin;
- avoid treating one comment as consensus;
- mention if discussion is mostly jokes, speculation, or off-topic;
- include thread links in output metadata;
- do not quote long user comments verbatim.

Sentiment enum:

```text
positive
mixed_positive
neutral
mixed
mixed_negative
negative
unclear
```

Confidence enum:

```text
high
medium
low
```

Confidence should depend on number of relevant threads, comment volume, and relevance strength.

---

## 12. CLI surface

Add a CLI command:

```bash
seismo community-research --source reddit --limit 200
```

Options:

```text
--source reddit              Community source. v1 supports only reddit.
--limit N                    Max entities to research this run.
--entity-id ID               Research one entity for debugging.
--force                      Ignore refresh cadence and run anyway.
--dry-run                    Print selected targets and queries, do not call Reddit.
--no-summarize               Fetch/search only; useful for API testing.
```

Example outputs:

```text
[community-research] reddit: selected 200 targets
[community-research] 143 found, 51 not_found, 6 failed
```

For `--entity-id`:

```text
[community-research] reddit entity=123 "vLLM": found 3 threads, status=found
```

---

## 13. Proposed module layout

```text
src/seismo/community/
  __init__.py
  targets.py        # due target selection
  queries.py        # query generation
  reddit.py         # Reddit client/search/fetch
  relevance.py      # deterministic result scoring
  summarize.py      # LLM prompt + structured summary
  runner.py         # orchestration + DB persistence
```

Add ORM model:

```python
class EntityCommunityResearch(Base):
    __tablename__ = "entity_community_research"
    ...
```

Add Alembic migration:

```text
alembic/versions/0007_community_research.py
```

Add API model fields:

```python
class CommunityThread(BaseModel):
    title: str
    subreddit: str
    url: str
    score: int | None
    comment_count: int | None
    created_at: datetime | None
    relevance_score: float | None

class CommunityResearch(BaseModel):
    source: str
    status: str
    summary: str
    sentiment: str | None
    confidence: str | None
    main_points: list[str]
    concerns: list[str]
    positive_signals: list[str]
    threads: list[CommunityThread]
    researched_at: datetime
```

Then add to `EntityDossier`:

```python
community: list[CommunityResearch] = []
```

v1 can return at most one Reddit result in the list. The list shape leaves room for Discord, GitHub Discussions, Lobsters, etc.

---

## 14. API changes

Modify `GET /entities/{entity_id}` to include latest community research rows.

Query logic:

```sql
SELECT source, status, result, model, researched_at
FROM entity_community_research
WHERE entity_id = :id
ORDER BY source, researched_at DESC
```

In Python, keep latest row per `source`.

Important:

- Use canonical entity id after `canonical_entity_id(...)`.
- Do not show rows for merged loser ids.
- Keep `as_of` behavior simple for v1: show latest community research row with `researched_at <= as_of`.

---

## 15. Dashboard changes

In `/entity/[id]`, add a Community section below the comprehension card/evidence area.

Display states:

- `found`: summary, sentiment/confidence label, main points, concerns, thread list.
- `not_found`: quiet empty state with last checked date.
- `failed`: quiet unavailable state; do not expose stack traces.
- no row: "Not researched yet" if the backend returns no community result.

Thread rows should show:

- subreddit;
- title;
- score;
- comment count;
- created date;
- outbound Reddit link.

The section should be evidence-first. The summary explains, but the links allow verification.

---

## 16. Idempotence and duplicate handling

Search results should be deduplicated by Reddit submission id.

Within one run:

- do not summarize the same Reddit thread twice for one entity;
- merge matched queries into `matched_queries`;
- keep the highest relevance score.

Across runs:

- append a new `entity_community_research` row when the entity is researched;
- include thread ids in the result;
- later code can compare previous thread ids to detect whether community discussion changed.

Future optimization:

```sql
CREATE TABLE community_threads (
  source TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  payload JSONB NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (source, thread_id)
);
```

Do not add this table in v1 unless duplicate thread fetches become expensive.

---

## 17. Rate limits and failure behavior

Rules:

1. All Reddit calls go through one client with a rate limiter.
2. Failures are isolated per entity.
3. Store `failed` rows only when useful; otherwise record run-level failure and retry later.
4. Missing credentials should make the command exit with a clear message.
5. `--dry-run` must not require Reddit credentials.

Suggested config:

```env
COMMUNITY_RESEARCH_DAILY_LIMIT=200
REDDIT_MAX_THREADS_PER_ENTITY=5
REDDIT_MAX_COMMENTS_PER_THREAD=20
REDDIT_SEARCH_QUERIES_PER_ENTITY=5
```

---

## 18. Tests

Minimum tests:

- query generation for GitHub/arXiv/HF/web entities;
- relevance scoring rejects ambiguous matches;
- relevance scoring accepts exact `owner/repo`, arXiv id, model id, or domain matches;
- target selector respects refresh cadence and `tracking_tier`;
- runner persists `found`, `not_found`, and `failed`;
- API returns latest community result per source;
- CLI `--dry-run` prints targets without credentials.

Use fake Reddit client fixtures. Do not call live Reddit in unit tests.

Optional integration test:

- gated by env var, e.g. `SEISMO_LIVE_REDDIT_TEST=1`;
- researches one known entity with a strict low limit.

---

## 19. Implementation phases

### Phase 1 - Storage and API contract

- Add Alembic migration for `entity_community_research`.
- Add SQLAlchemy model.
- Add Pydantic response models.
- Add `community` field to entity dossier response.
- Return latest stored community row from `GET /entities/{id}`.

No Reddit calls yet.

### Phase 2 - Target selection and dry run

- Add `src/seismo/community/targets.py`.
- Add `src/seismo/community/queries.py`.
- Add CLI command with `--dry-run`.
- Verify selected due entities and generated queries.

No Reddit calls yet.

### Phase 3 - Reddit search and relevance

- Add Reddit client.
- Add deterministic relevance scoring.
- Fetch submissions only.
- Persist `not_found` or raw candidate metadata in debug logs.

No LLM summary yet.

### Phase 4 - Comment fetch and summarization

- Fetch bounded top comments for relevant submissions.
- Add summarizer with structured output.
- Persist final `found`/`not_found` rows.

### Phase 5 - Dashboard UI

- Render community section on entity page.
- Link to Reddit threads.
- Add empty/failed states.

### Phase 6 - Daily operations

- Add the command to daily script/systemd timer.
- Start with small limit, e.g. 50-100/day.
- Monitor failures and rate limits.
- Increase limit when stable.

---

## 20. Definition of done

- [ ] `entity_community_research` migration and ORM model exist.
- [ ] `seismo community-research --source reddit --dry-run` selects due entities and prints queries.
- [ ] `seismo community-research --source reddit --entity-id X` can research one entity.
- [ ] Runner stores `found`, `not_found`, or `failed` rows.
- [ ] Entity dossier API returns latest community research.
- [ ] Dashboard displays summary and Reddit thread links.
- [ ] Daily job includes community research with a bounded `--limit`.
- [ ] Unit tests cover query generation, relevance scoring, target cadence, persistence, and API projection.
- [ ] Missing Reddit credentials produce a clear operational message.

---

## 21. Non-goals for v1

- Do not discover new entities from Reddit.
- Do not ingest all Reddit comments globally.
- Do not support Discord.
- Do not scrape Reddit HTML.
- Do not treat Reddit sentiment as a numeric trading/investment signal.
- Do not refresh every entity every day.
- Do not hide source links behind an opaque summary.

