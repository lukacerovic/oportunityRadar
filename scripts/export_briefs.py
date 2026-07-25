"""Export per-entity brief files for the knowledge graph (graphify corpus).

One markdown file per signal-bearing entity — deterministic facts from the DB plus the
LLM comprehension card where one exists. Cross-references between entities are written
as explicit canonical names so graph extraction can link them (cited papers, same-owner
siblings, shared themes).

Slice: entities with >=2 evidence sources, a comprehension card, a typed graph edge,
OpenRouter usage, or non-dormant momentum. Everything else is dormant single-source
noise at current scale.

Usage: uv run python scripts/export_briefs.py [--out briefs]
"""

from __future__ import annotations

import argparse
import re
import shutil
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

from seismo.db import session_scope

SLICE_SQL = """
select e.id, e.canonical_name, e.entity_type, e.category, e.attrs
from entities e
where e.merged_into is null and e.id in (
  select entity_id from (
    select el.entity_id
    from entity_links el join raw_events re on re.id = el.raw_event_id
    group by el.entity_id having count(distinct re.source) >= 2
  ) m
  union select entity_id from comprehension_cards
  union select entity_id from entity_metrics_daily where metric = 'or_tokens_wk'
  union select src_entity_id from entity_graph_edges
  union select dst_entity_id from entity_graph_edges
  union select entity_id from momentum_states where state != 'dormant'
)
"""


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or "entity"


def _event_line(source: str, event_type: str, occurred, payload: dict) -> str | None:
    day = occurred.date().isoformat()
    p = payload or {}
    if source == "hn":
        title = p.get("title") or "(untitled)"
        pts = p.get("points") or p.get("score")
        return f"- {day} — Hacker News: \"{title}\"" + (f" ({pts} points)" if pts else "")
    if source == "github":
        repo = p.get("full_name") or p.get("repo") or p.get("name")
        return f"- {day} — GitHub {event_type}: {repo}" if repo else None
    if source == "hf":
        mid = p.get("model_id") or p.get("id")
        return f"- {day} — Hugging Face {event_type}: {mid}" if mid else None
    if source == "openrouter":
        if event_type == "or_rankings":
            tokens, cat = p.get("tokens"), p.get("category")
            return f"- {day} — OpenRouter weekly rankings: {tokens:,} tokens ({cat})"
        return f"- {day} — OpenRouter listing: {p.get('model_id')}"
    if source == "arxiv":
        return f"- {day} — arXiv paper: \"{p.get('title')}\"" if p.get("title") else None
    if source == "pypi":
        return f"- {day} — PyPI {event_type}: {p.get('name') or p.get('project')}"
    if source == "web":
        return f"- {day} — Web launch page observed"
    return f"- {day} — {source} {event_type}"


def _looks_like_a_prior_export(root: Path) -> bool:
    """True only if every entry under ``root`` is itself a directory of ``.md`` files — the exact
    shape this script produces. Refuses to blow away anything else the caller pointed --out at."""
    for child in root.iterdir():
        if not child.is_dir():
            return False
        if any(f.suffix != ".md" for f in child.iterdir()):
            return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="briefs")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Delete --out even if it doesn't look like a prior export.",
    )
    args = ap.parse_args()
    out_root = Path(args.out).resolve()
    guarded = {Path.cwd().resolve(), Path.home().resolve(), Path(__file__).resolve().parent.parent}
    if out_root in guarded:
        raise SystemExit(f"refusing to delete {out_root} — looks like cwd/home/repo root")
    if out_root.exists():
        if not args.force and not _looks_like_a_prior_export(out_root):
            raise SystemExit(
                f"{out_root} exists and doesn't look like a prior brief export (expects only "
                "category subdirectories of .md files) — pass --force to delete it anyway"
            )
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    with session_scope() as s:
        q = lambda sql, **kw: s.execute(text(sql), kw).all()  # noqa: E731

        entities = q(SLICE_SQL)
        ids = [r[0] for r in entities]
        id_set = set(ids)
        name_of = {r[0]: r[1] for r in entities}

        # Bulk-load everything keyed by entity_id.
        sources: dict[int, set[str]] = defaultdict(set)
        events: dict[int, list] = defaultdict(list)
        for eid, src, etype, occ, payload in q(
            """
            select el.entity_id, re.source, re.event_type, re.occurred_at, re.payload
            from entity_links el join raw_events re on re.id = el.raw_event_id
            where el.entity_id = any(:ids)
            order by re.occurred_at
            """,
            ids=ids,
        ):
            sources[eid].add(src)
            events[eid].append((src, etype, occ, payload))

        metrics: dict[int, dict[str, tuple]] = defaultdict(dict)
        for eid, metric, day, value in q(
            """
            select distinct on (entity_id, metric) entity_id, metric, day, value
            from entity_metrics_daily where entity_id = any(:ids)
            order by entity_id, metric, day desc
            """,
            ids=ids,
        ):
            metrics[eid][metric] = (day, value)

        momentum: dict[int, tuple] = {}
        for eid, day, state, score in q(
            """
            select distinct on (entity_id) entity_id, day, state, score
            from momentum_states where entity_id = any(:ids)
            order by entity_id, day desc
            """,
            ids=ids,
        ):
            momentum[eid] = (day, state, score)

        maturity: dict[int, list] = defaultdict(list)
        for eid, stage, promoted in q(
            "select entity_id, stage, promoted_at from maturity_promotions"
            " where entity_id = any(:ids) order by promoted_at",
            ids=ids,
        ):
            maturity[eid].append((stage, promoted))

        themes: dict[int, list[str]] = defaultdict(list)
        for eid, slug in q(
            """
            select et.entity_id, t.name from entity_themes et
            join themes t on t.id = et.theme_id where et.entity_id = any(:ids)
            """,
            ids=ids,
        ):
            themes[eid].append(slug)

        cards: dict[int, dict] = {}
        for eid, card in q(
            """
            select distinct on (entity_id) entity_id, card
            from comprehension_cards where entity_id = any(:ids) and status = 'ok'
            order by entity_id, version desc
            """,
            ids=ids,
        ):
            cards[eid] = card

        edges_out: dict[int, list] = defaultdict(list)
        edges_in: dict[int, list] = defaultdict(list)
        for src, dst, etype in q(
            "select src_entity_id, dst_entity_id, edge_type from entity_graph_edges"
        ):
            if src in id_set and dst in id_set:
                edges_out[src].append((etype, dst))
                edges_in[dst].append((etype, src))

        # Same-owner siblings from the "owner/name" convention in canonical names.
        by_owner: dict[str, list[int]] = defaultdict(list)
        for eid in ids:
            if "/" in name_of[eid]:
                by_owner[name_of[eid].split("/", 1)[0].lower()].append(eid)

        written = 0
        for eid, name, etype_, category, _attrs in entities:
            cat_dir = out_root / (category or "uncategorized")
            cat_dir.mkdir(exist_ok=True)
            card = cards.get(eid)
            mom = momentum.get(eid)
            lines: list[str] = ["---"]
            lines.append(f"entity_id: {eid}")
            lines.append(f"name: \"{name}\"")
            lines.append(f"type: {etype_}")
            lines.append(f"category: {category or 'uncategorized'}")
            if sources[eid]:
                lines.append(f"sources: [{', '.join(sorted(sources[eid]))}]")
            if mom:
                lines.append(f"momentum: {mom[1]} ({mom[0]})")
            if maturity[eid]:
                lines.append(f"maturity: {maturity[eid][-1][0]}")
            if themes[eid]:
                lines.append(f"themes: [{', '.join(sorted(themes[eid]))}]")
            lines.append("---")
            lines.append("")
            lines.append(f"# {name}")
            lines.append("")

            if card:
                lines.append("## What it is")
                lines.append(card.get("what_it_is") or card.get("function") or "")
                if card.get("who_is_behind"):
                    lines.append("")
                    lines.append(f"**Who is behind it:** {card['who_is_behind']}")
                if card.get("claimed_advantage"):
                    lines.append(f"**Claimed advantage:** {card['claimed_advantage']}")
                if card.get("replaces_or_enables"):
                    lines.append(f"**Replaces or enables:** {card['replaces_or_enables']}")
                if card.get("open_questions"):
                    oq = card["open_questions"]
                    oq = "; ".join(oq) if isinstance(oq, list) else str(oq)
                    lines.append(f"**Open questions:** {oq}")
                lines.append("")

            evs = events[eid]
            if evs:
                lines.append("## Evidence timeline")
                # First and most recent events per source, capped, oldest first.
                picked: list = []
                seen_src: set[str] = set()
                for e in evs:
                    if e[0] not in seen_src:
                        picked.append(e)
                        seen_src.add(e[0])
                picked.extend(e for e in evs[-6:] if e not in picked)
                for src, et, occ, payload in picked[:10]:
                    line = _event_line(src, et, occ, payload)
                    if line:
                        lines.append(line)
                lines.append("")

            if metrics[eid]:
                lines.append("## Latest metrics")
                for metric, (day, value) in sorted(metrics[eid].items()):
                    lines.append(f"- {metric}: {value:,.0f} (as of {day})")
                lines.append("")

            conn: list[str] = []
            for et, dst in edges_out[eid]:
                conn.append(f"- {et} → \"{name_of[dst]}\"")
            for et, src_ in edges_in[eid]:
                conn.append(f"- {et} ← \"{name_of[src_]}\"")
            if "/" in name:
                owner = name.split("/", 1)[0]
                sibs = [i for i in by_owner[owner.lower()] if i != eid]
                if sibs:
                    names = ", ".join(f"\"{name_of[i]}\"" for i in sibs[:8])
                    conn.append(f"- same owner ({owner}) as: {names}")
            if conn:
                lines.append("## Connections")
                lines.extend(conn)
                lines.append("")

            (cat_dir / f"{eid}-{_slug(name)}.md").write_text(
                "\n".join(lines), encoding="utf-8"
            )
            written += 1

    print(f"wrote {written} briefs to {out_root}/")


if __name__ == "__main__":
    main()
