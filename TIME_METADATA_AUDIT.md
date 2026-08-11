# Time metadata audit — what we stamp vs. what the source actually gives

*2026-08-05. Every "available" column below was verified with a live API call, not read from docs.
Row counts are from the dev DB.*

Invariant #1 already requires `occurred_at` to be **source time** and `ingested_at` to be our time.
This audit checks which collectors actually honour that, and designs a rule for the events where no
source time exists.

---

## 1. The audit

| event_type | rows | `occurred_at` today | source actually offers | verdict |
|---|---:|---|---|---|
| `repo_discovered` | 14,159 | `repo.created_at` | `created_at` | ✅ correct |
| `story` (HN) | 3,501 | `created_at_i` | `created_at_i` | ✅ correct |
| `paper_published` | 2,035 | `published` | `published`, `updated` | ✅ correct |
| `model_discovered` | 84 | `createdAt` | `createdAt` | ✅ correct |
| `or_rankings` | 18 | the ranked day | the day | ✅ correct |
| `or_model_listed` | 10 | source time | ✓ | ✅ correct |
| `repo_snapshot` | 15,994 | `now()` | — | ✅ correct **by definition** |
| `model_snapshot` | 302 | `now()` | — | ✅ correct by definition |
| `pypi_snapshot` | — | `now()` | — | ✅ correct by definition |
| `repo_contributors` | — | `now()` | — | ✅ correct by definition (current aggregate) |
| `wikidata_entity` | — | `fetched_at` | revision ts exists | ⚠️ minor |
| `repo_readme` | 1,222 | `now()` | **README last commit — verified `2026-06-12`** | ⚠️ real time exists, +1 API call |
| `model_readme` | 97 | `now()` | **`lastModified` — verified `2024-10-16`** | ⚠️ real time exists, **free**, same response |
| `launch_page` | 19 | `now()` | usually none | ⚠️ acceptable, must be labelled |
| **`pypi_metadata`** | — | `now()` | **full release history — 508 versions, first `2022-10-25`** | ❌ **big miss** |
| **`hn_discussion`** | 61 | `now()` | **author + created_at + points per comment** | ❌ **broken** |
| **community `comments`** | 0 | thread `created_at` ✅ | **same per-comment fields** | ❌ **same bug, Luka's layer** |

## 2. The three real problems

### `pypi_metadata` — we throw away the entire release history

`https://pypi.org/pypi/langchain/json` returns **508 versions**, each with
`upload_time_iso_8601`. First-ever release: `2022-10-25T04:10:02Z`.

We stamp `now()` and keep only `requires_dist` / `project_urls` / `summary`.

This is not just a timestamp problem. **First-release date and release cadence are direct maturity
signals** — exactly what the ladder's `usable_artifact` → `distribution` rungs are trying to infer.
We're fetching the answer and discarding it.

### `hn_discussion` — author and time available, deliberately dropped

Verified live on a current front-page story, per comment:

```
['author', 'children', 'created_at', 'created_at_i', 'id', 'options',
 'parent_id', 'points', 'story_id', 'text', 'title', 'type', 'url']
```

`_top_comments` (`collectors/launches.py:212`) reads only `child.get("text")`, then
`"\n\n".join(comments)` flattens 12 comments into one blob under a single `now()` stamp.

`WAVES_HANDOFF.md` already excludes this event type from observer detection for exactly this reason.
The fix removes that exclusion.

### Luka's community layer has the same bug

`CommunityThread` (`community/relevance.py:24`) captures thread-level `created_at` correctly — but
declares `comments: list[str]`. Authors and per-comment timestamps are dropped at the same point,
from the same APIs.

This matters more than it looks for the wave feature: "someone saw it earlier" needs an author and a
time **per utterance**. A thread created in January can carry the decisive comment in March. Thread
time answers the wrong question.

## 3. The design — a `time_basis` contract

The deeper problem isn't any single collector. It's that **`occurred_at` is currently ambiguous** —
there is no way to tell "this is real source time" from "this is when we happened to fetch it". Every
downstream consumer has to know by heart which types are trustworthy, and `waves/observers.py`
literally maintains a hand-written `_SOURCES` whitelist because of it. That doesn't scale and will
quietly mislead someone.

Proposal: every draft declares what its timestamp *means*.

```python
payload["time_basis"] = "source" | "observation" | "fetched"
```

| basis | meaning | `occurred_at` is | examples |
|---|---|---|---|
| `source` | the thing happened then, per the source | trustworthy for lead time, replay, ordering | `repo_discovered`, `story`, `paper_published`, fixed `pypi_metadata`, fixed `hn_discussion` |
| `observation` | we measured a level at this moment; that IS the event | trustworthy — a snapshot's event time is the observation | `repo_snapshot`, `model_snapshot`, `repo_contributors` |
| `fetched` | no source time exists; this is when we looked | **never** valid for lead time or ordering | `launch_page` |

The point of separating `observation` from `fetched`: today both look like `now()`, but a snapshot's
`now()` is *correct* while a launch page's `now()` is *a shrug*. Collapsing them is what makes the
current state unauditable.

Then `waves/observers.py` filters on `time_basis == "source"` by contract instead of a whitelist, and
any new collector is automatically included or excluded correctly without anyone remembering to
update a list.

## 4. Ordering, by value per unit of work

1. **`model_readme` → `lastModified`** — free, same API response, one line.
2. **`pypi_metadata` → release history** — free, same response, and unlocks a genuine maturity signal.
3. **`hn_discussion` → per-comment author/time** — one function, unblocks wave observers immediately.
4. **`time_basis` on every draft** — mechanical, touches every collector, prevents the whole class of bug.
5. **community `comments: list[str]` → structured** — same fix as #3 but in Luka's module; coordinate first.
6. **`repo_readme` → README last-commit date** — costs +1 GitHub call per repo (5,000/hr budget, 1,222 events). Do last, or skip and label `fetched`.

## 5. What about the 61 existing `hn_discussion` rows

Raw events are immutable (invariant #1), so they don't get rewritten. They keep `time_basis` absent,
which downstream code should treat as "unknown, not trustworthy" — the same as `fetched`. New events
are correct from the fix onward. Observers already skip these 61, so nothing regresses.
