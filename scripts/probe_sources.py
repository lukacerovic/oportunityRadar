"""Phase-0 source probe — live-check every candidate in ``SOURCE_EXPANSION.md``.

Same discipline as the 2026-07-23 market-source spike recorded in ``DECISIONS.md``: hit each
candidate for real, keep the raw payload as a fixture, and record a verdict. A source that fails
here is **dropped, not worked around** — that rule is what kept Reddit and OpenRouter out.

This must run on a machine with open outbound network. It is deliberately *not* wired into
``daily.sh`` or the test suite: it makes real requests to third parties and exists to inform a
decision once, not to run on a schedule.

    uv run python scripts/probe_sources.py             # human-readable table
    uv run python scripts/probe_sources.py --json      # machine-readable
    uv run python scripts/probe_sources.py --save      # also write tests/fixtures/probe/*.json

Every probe is best-effort and isolated: one dead host never stops the rest, exactly like the
collector runner. What it reports is reachability and shape — whether a source is *worth* building
is still a human judgment, and the numbers below are the evidence for it, not the answer.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "probe"
TIMEOUT = 20.0
UA = "seismograph-source-probe (contact: repo owner)"


@dataclass
class Probe:
    """One candidate source. ``expect`` names the payload keys that must be present for the source
    to be usable — a 200 with the wrong shape is a NO-GO, not a pass."""

    key: str
    what_for: str  # discovery | linking | lead-time | grading
    url: str
    expect: tuple[str, ...] = ()
    note: str = ""
    headers: dict[str, str] = field(default_factory=dict)


PROBES: tuple[Probe, ...] = (
    # --- lead time: authored + timestamped text ---------------------------------
    Probe(
        "hn_comments",
        "lead-time",
        "https://hn.algolia.com/api/v1/search_by_date"
        "?tags=comment&query=agent&hitsPerPage=3",
        expect=("hits",),
        note="THE high-value one. Same endpoint the story collector already uses, tags=comment. "
        "Check hits[].author, hits[].created_at_i, hits[].comment_text are all present.",
    ),
    Probe(
        "lobsters",
        "lead-time",
        "https://lobste.rs/newest.json",
        note="Small but high signal-to-noise. Needs submitter handle + created_at to qualify.",
    ),
    Probe(
        "substack_feed",
        "lead-time",
        "https://www.interconnects.ai/feed",
        note="Already a recorded GO in DECISIONS.md (2026-07-23) and never built. XML, not JSON.",
    ),
    # --- grading: adoption that is hard to game ---------------------------------
    Probe(
        "npm_downloads",
        "grading",
        "https://api.npmjs.org/downloads/point/last-week/langchain",
        expect=("downloads", "package"),
        note="Closes the 'JS waves are permanently unmeasurable' hole.",
    ),
    Probe(
        "depsdev_npm",
        "grading",
        "https://api.deps.dev/v3alpha/systems/npm/packages/langchain",
        note="Dependent counts beat downloads: a dependent is a decision, a download is often CI.",
    ),
    Probe(
        "crates_io",
        "grading",
        "https://crates.io/api/v1/crates/tokio",
        expect=("crate",),
        headers={"User-Agent": UA},
        note="Verified reachable 2026-08-07. Carries downloads + reverse dependency counts.",
    ),
    Probe(
        "pypistats",
        "grading",
        "https://pypistats.org/api/packages/langchain/recent",
        note="Cross-check for the existing PyPI collector; not a replacement for it.",
    ),
    # --- discovery: entities entering the system --------------------------------
    Probe(
        "ecosystems_packages",
        "discovery",
        "https://packages.ecosyste.ms/api/v1/registries/pypi.org/packages/langchain",
        note="109 registries, ~5000 req/hr. LICENSING IS UNSETTLED — see DATA_SOURCE_OPTIONS.md; "
        "their /commercial and /terms pages contradict each other. Resolve before building.",
    ),
    Probe(
        "ecosystems_repos",
        "discovery",
        "https://repos.ecosyste.ms/api/v1/hosts/GitHub/repositories/langchain-ai%2Flangchain",
        note="Discovery without depending on the author having tagged their repo.",
    ),
    Probe(
        "gharchive",
        "discovery",
        "https://data.gharchive.org/2026-07-01-15.json.gz",
        note="Already used for backfill (collectors/backfill_gharchive.py). HEAD only — the file "
        "is large, and this probe just proves reachability.",
    ),
    # --- reference / momentum ---------------------------------------------------
    Probe(
        "openalex",
        "linking",
        "https://api.openalex.org/works?filter=from_publication_date:2026-07-01&per-page=1",
        note="Citation velocity — a momentum signal the system lacks entirely.",
    ),
)


def _run_one(client: httpx.Client, p: Probe) -> dict[str, Any]:
    result: dict[str, Any] = {"key": p.key, "for": p.what_for, "note": p.note}
    try:
        # gharchive files are large; reachability is all this needs to establish.
        method = "HEAD" if p.url.endswith(".gz") else "GET"
        resp = client.request(method, p.url, headers={"User-Agent": UA, **p.headers})
    except httpx.HTTPError as exc:
        return {**result, "status": None, "verdict": "UNREACHABLE", "detail": str(exc)[:160]}

    result["status"] = resp.status_code
    result["bytes"] = len(resp.content)
    if resp.status_code >= 400:
        return {**result, "verdict": "NO-GO", "detail": resp.text[:160]}

    if method == "HEAD" or not resp.headers.get("content-type", "").startswith("application/json"):
        # XML feeds and binary archives: reachability + non-empty is the whole check here.
        return {**result, "verdict": "REACHABLE", "detail": resp.headers.get("content-type", "")}

    try:
        payload = resp.json()
    except ValueError:
        return {**result, "verdict": "NO-GO", "detail": "200 but body is not JSON"}

    missing = [k for k in p.expect if not (isinstance(payload, dict) and k in payload)]
    if missing:
        # A 200 with the wrong shape is a failure. Silently accepting it is how a collector ends
        # up writing empty rows for weeks before anyone notices.
        return {**result, "verdict": "NO-GO", "detail": f"missing keys: {missing}"}

    result["keys"] = sorted(payload)[:12] if isinstance(payload, dict) else "list"
    return {**result, "verdict": "GO"}


def main() -> int:
    save = "--save" in sys.argv
    as_json = "--json" in sys.argv

    results = []
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for p in PROBES:
            res = _run_one(client, p)
            results.append(res)
            if save and res["verdict"] in ("GO", "REACHABLE"):
                FIXTURES.mkdir(parents=True, exist_ok=True)
                try:
                    body = client.get(p.url, headers={"User-Agent": UA, **p.headers}).text[:20000]
                    (FIXTURES / f"{p.key}.txt").write_text(body)
                except httpx.HTTPError:
                    pass

    if as_json:
        print(json.dumps(results, indent=2))
        return 0

    width = max(len(r["key"]) for r in results)
    for r in results:
        status = r.get("status") or "—"
        print(f"{r['verdict']:<12} {r['key']:<{width}}  {status:<5} [{r['for']}]")
        if r.get("detail"):
            print(f"{'':<12} {'':<{width}}  {r['detail'][:100]}")
    go = sum(1 for r in results if r["verdict"] == "GO")
    print(f"\n{go}/{len(results)} usable. Record each verdict in DECISIONS.md.")
    print("Drop rather than work around — that rule is what kept Reddit and OpenRouter out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
