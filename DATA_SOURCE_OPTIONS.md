# Data source options — what we can actually use

*Research + live verification 2026-07-28. Follow-up to `COMPETITIVE_LANDSCAPE.md`.
Everything marked ✅ VERIFIED was curl-tested from this machine, not taken from docs.*

## TL;DR

Four free, officially-public sources fill three of our real gaps at near-zero legal risk.
**RapidAPI is a no** — not on principle, on evidence. And one existing dependency (GH Archive)
got a clean bill of health after a scare.

---

## ✅ VERIFIED LIVE — worth building

### 1. Wayback CDX API → commercialization evidence (the 5th evidence type, currently missing)

The question "when did this project start charging money?" is answerable directly:

```bash
curl "https://web.archive.org/cdx/search/cdx?url=openrouter.ai/pricing&output=json&fl=timestamp,original,statuscode"
→ ["20250130131137","https://openrouter.ai/pricing","200"]   # first capture
```

That timestamp *is* the commercialization event. Free, no auth, no key.
Caveats: ~1 req/sec practical limit (nonprofit, be polite), no SLA, and one of my two test
calls returned a 504 — needs retry/backoff like any flaky endpoint. Archived content is
immutable, so cache aggressively and never re-fetch the same snapshot.

This is the **best effort-to-value ratio of anything researched.** It unlocks the top rung of
the maturity ladder (`commercialization`) that v1 currently can't reach (A-5).

### 2. Public ATS job boards → commitment evidence (also missing)

Greenhouse / Lever / Ashby publish their customers' job boards as unauthenticated public JSON.
This is officially documented, first-party data — the company's own careers page in machine-readable
form. Not scraping.

```bash
curl "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs"   → 200, 417 jobs
curl "https://api.ashbyhq.com/posting-api/job-board/openai"         → 200
curl "https://api.lever.co/v0/postings/{company}?mode=json"         → 200
```

AI startups overwhelmingly use exactly these three. The work isn't the fetching — it's building
a company → ATS-slug resolver. That means it only works for entities we *already* track, so it's
a corroboration signal, not a discovery mechanism.

**Free bonus with zero new integration:** HN's monthly "Who is Hiring" thread is already inside
our existing HN collector's reach. Each top-level comment is a self-reported hiring signal. Cheaper
cross-check than the ATS work, catches earlier-stage companies not yet on a formal ATS.

### 3. ecosyste.ms → dependency graph (powers the `dependency_risk` mechanism)

Real, bidirectional, and much bigger than expected. Verified live:

```
langchain (pypi):  1,062 dependent packages · 18,663 dependent repos · 319M downloads
vllm (pypi):          46 dependent packages ·      5 dependent repos
```

That contrast is itself informative — it's a *structural* difference between a library everything
builds on and a runtime people deploy but don't import. We currently have no way to see that.

- **Rate limit verified: 15,000 req/hr** on the "polite" tier — you get it automatically by putting
  an email in the User-Agent (OpenAlex convention). Anonymous is 5,000/hr. No API key needed.
- Covers **100 registries** (npm, crates, Go, Maven, RubyGems, Docker…), not just PyPI. It does
  **not** index HuggingFace, so it can't duplicate our HF collector.
- Actively maintained — commits on the day of research, funded by Schmidt Futures + Open Source
  Collective, same founder as libraries.io.

**Two warnings:**
- `papers.ecosyste.ms` is **frozen since 2023** (17,540 records, all Oct–Nov 2023, PyPI/CRAN/
  Bioconductor only — it's just an import of a CZI dataset, not original work). The live successor is
  `science.ecosyste.ms` (374k projects, keyed by GitHub URL, Crossref+OpenAlex-sourced). If we want
  paper↔repo linkage from them, that's the one — but its matching methodology is unpublished, so
  spot-check before trusting it for entity resolution.
- **Licensing has a real contradiction on their own site:** the data is CC BY-SA 4.0 (commercial OK,
  ShareAlike applies), but their generic ToS page says no commercial use without written permission.
  Probably website-boilerplate vs. data-license, but given our provenance discipline —
  **email support@ecosyste.ms and get it in writing before this ships.** Two specific questions:
  does ShareAlike force us to publish derived momentum scores, and does the ToS restriction apply to
  the API or just the site.

### 4. OpenAlex → citation velocity (a momentum signal we completely lack)

CC0 public domain, 240M works, 2.5B citation links, with `cited_by_count` and institutional
affiliations per work. Right now our arXiv papers have no velocity signal at all — this fixes it.

**Changed in Feb 2026:** the live API now needs a key and is usage-priced ($1/day free credit).
The **free monthly CC0 bulk snapshot is still free** — use that path, not live API calls.
Friction: no first-class arXiv-ID lookup, so matching is DOI/title-based.

---

## ❌ RapidAPI — no, and the reasons are concrete

Not a principled objection. Three specific findings:

1. **The platform is in run-off.** Acquired by **Nokia in Nov 2024** for the telecom-API tech, not
   the marketplace. Per the acquirer's own reporting: peak ~4M users / 40k APIs → **"thousands" of
   active users and "hundreds" of active APIs** at acquisition. CEO left 2023, ~82% headcount cut.
   Their marketing pages still quote the peak numbers. Building a dependency on this is betting
   against the platform's own trajectory.

2. **Every job API there is an unauthorized scraper.** JSearch — the most-installed one — scrapes
   Google for Jobs, which aggregates LinkedIn/Indeed/Glassdoor. None are official feeds.
   The legal record matters here: hiQ v. LinkedIn is widely misremembered as "scraping is legal" —
   it ended in a **2022 settlement where hiQ was permanently enjoined, had to delete all derived
   data and algorithms, and paid $500k**, with the court finding LinkedIn's ToS unambiguously
   prohibits scraping on breach-of-contract grounds. In 2025 **Proxycurl** — a paid commercial
   scraping API, structurally identical to what's on RapidAPI — settled with LinkedIn and had to
   **permanently delete its entire dataset.** A source we depend on can go to zero overnight for
   reasons we never see coming.

3. **It breaks our core design rule.** "Every claim traces to a raw event" cannot survive an
   unauditable middleman. We can't verify what a reseller did to the data between the source and us,
   and the free tiers reportedly serve **cached/test data rather than erroring** — degradation our
   pipeline wouldn't detect.

**The narrow exception:** some legitimate vendors (Crunchbase, Twilio, Azure) distribute their *own*
API through RapidAPI purely as a billing gateway. That's fine — but evaluate the vendor, never treat
"found on RapidAPI" as a signal of legitimacy. Nothing in that category helps our two gaps anyway.

## On "stealing" data from the competitors

Short version: unnecessary, and it would cost us the thing that makes us different.

The paywalled vendors (PitchBook, CB Insights, AlphaSense, Tracxn) all have anti-scraping ToS and
legal teams — PitchBook actively bans accounts that try. But the real argument isn't risk, it's that
**their data is worse for our purpose than what's free.** Their value is curated funding/financial
records; ours is upstream build-signal they don't have. Scraping them would import a provenance
black box into the one system whose entire selling point is that every claim traces to a raw event.

Everything ranked above is CC0, CC BY-SA, or an officially-public first-party endpoint. There's
enough genuinely open data here to fill all three gaps without touching anything grey.

---

## ✅ Existing dependency cleared: GH Archive is fine

A public GitHub discussion claims the GH Archive **BigQuery mirror** has been stale ~2 years.
Verified this directly — **it doesn't affect us.** We use the file endpoint
(`backfill_gharchive.py:27` → `https://data.gharchive.org/{stamp}.json.gz`), not BigQuery:

```
2026-07-26-12.json.gz → HTTP 200, 20,976,325 bytes
2026-07-25-12.json.gz → HTTP 200, 20,988,970 bytes
```

Current, full-size, healthy. No action needed. Worth knowing if we ever consider the BigQuery path.

---

## Deprioritized (researched, not worth it)

| Source | Why not |
|---|---|
| **GitHub Innovation Graph** | CC0 and genuinely open, but country-level **quarterly** aggregates. Granularity mismatch with an entity-level daily system. |
| **Common Crawl** | Monthly *sample* of the web, not continuous per-domain coverage; real Athena compute cost. Wayback CDX answers the same pricing question per-domain, cheaper and better. |
| **Software Heritage** | Narrow provenance-forensics use case, bulk extraction explicitly forbidden. One-off lookup tool, not a feed. |
| **Papers with Code** | Dead since 2025. Static community mirrors survive on GitHub/HF — one-time historical enrichment only. |
| **ROSS Index** | Only ~20 entities/quarter and startup-only, so not a feed — but genuinely useful as an **independent cross-check**: where their star-growth ranking and our momentum states disagree, that's a signal worth investigating. Note **CC BY-ND** — internal use fine, republishing a modified version is not. |
| **npm / Homebrew download APIs** | Legitimate and cheap, just lower priority than the three gap-fillers. Easy win later — extends usage evidence beyond PyPI. |
| **Libraries.io / Tidelift dumps** | Overlaps ecosyste.ms for dependency data; heavier ingestion (~400M rows). Prefer ecosyste.ms first. |

---

## Suggested order — but see the blocker first

**⚠️ Blocker:** per the standing decision from 2026-07-25, hold off on new collectors until Luka's
community-comments component lands, so the two efforts don't collide. Everything below is a *new
collector*. Worth confirming with Luka before starting — or picking only #0, which isn't a collector.

0. **Email ecosyste.ms about licensing** — zero code, unblocks #3, do it now regardless.
1. **Wayback CDX pricing watcher** — smallest build, unlocks the missing top ladder rung.
2. **HN "Who is Hiring" parsing** — extends an existing collector rather than adding one; least
   likely to collide with Luka's work since it's the same HN surface (coordinate on this specifically).
3. **ecosyste.ms dependency pull** — biggest single capability gain (`dependency_risk` becomes real).
4. **ATS job boards** — needs the slug-resolver first; most work of the four.
5. **OpenAlex citation velocity** — real signal, but bulk-snapshot ingestion is the heaviest lift.
