"""Measure whether the wave layer can actually produce anything — the funnel, with real numbers.

Every plan on this branch (`WAVE_PLAN`, `LEAD_TIME_PLAN`, `TAXONOMY_PLAN`, `SOURCE_EXPANSION`) rests
on estimates taken from a `STATE.md` snapshot. This replaces the estimates with measurements.

Read-only. Touches no table, spends nothing, runs in seconds. Safe against a live database.

    uv run python scripts/measure_readiness.py
    uv run python scripts/measure_readiness.py --window 30 --max-age 180

The one number that matters most is **carded young entities**: waves only look at entities younger
than ``--max-age`` whose first evidence falls inside ``--window``, so the carding backlog that
actually blocks the feature is far smaller than the whole-universe backlog. If that number is in the
hundreds it is an afternoon on a local model; if it is in the thousands it is a budget decision.
Guessing which one it is has been blocking every downstream choice.
"""

from __future__ import annotations

import argparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.db import session_scope


def _scalar(s: Session, sql: str, **params: object) -> int:
    return int(s.execute(text(sql), params).scalar() or 0)


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:5.1f} %" if whole else "    — "


def _bar(part: int, whole: int, width: int = 28) -> str:
    filled = round(width * part / whole) if whole else 0
    return "█" * filled + "·" * (width - filled)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=30, help="wave_window_days")
    ap.add_argument("--max-age", type=int, default=180, help="wave_max_age_days")
    args = ap.parse_args()

    with session_scope() as s:
        total = _scalar(s, "SELECT count(*) FROM entities WHERE merged_into IS NULL")
        carded = _scalar(
            s,
            "SELECT count(DISTINCT entity_id) FROM comprehension_cards WHERE status = 'ok'",
        )
        # An edge with a NULL endpoint anchors on a bare concept and cannot link two entities,
        # so it is excluded here — counting it would overstate how connected the graph is.
        edged = _scalar(
            s,
            """
            SELECT count(*) FROM (
                SELECT src_entity_id AS id FROM entity_semantic_edges
                 WHERE src_entity_id IS NOT NULL AND dst_entity_id IS NOT NULL
                UNION
                SELECT dst_entity_id FROM entity_semantic_edges
                 WHERE src_entity_id IS NOT NULL AND dst_entity_id IS NOT NULL
            ) x
            """,
        )
        edges_total = _scalar(s, "SELECT count(*) FROM entity_semantic_edges")

        # The wave candidate population: first evidence inside the window, and young enough.
        young = """
            SELECT e.id
            FROM entities e
            JOIN entity_links l ON l.entity_id = e.id AND l.rule = 'attach'
            JOIN raw_events r ON r.id = l.raw_event_id
            WHERE e.merged_into IS NULL
            GROUP BY e.id
            HAVING MIN(r.occurred_at) > now() - make_interval(days => :window)
               AND MIN(r.occurred_at) > now() - make_interval(days => :max_age)
        """
        in_window = _scalar(
            s, f"SELECT count(*) FROM ({young}) y", window=args.window, max_age=args.max_age
        )
        young_carded = _scalar(
            s,
            f"""SELECT count(*) FROM ({young}) y
                WHERE EXISTS (SELECT 1 FROM comprehension_cards c
                              WHERE c.entity_id = y.id AND c.status = 'ok')""",
            window=args.window,
            max_age=args.max_age,
        )
        young_edged = _scalar(
            s,
            f"""SELECT count(*) FROM ({young}) y
                WHERE EXISTS (SELECT 1 FROM entity_semantic_edges se
                              WHERE se.src_entity_id = y.id OR se.dst_entity_id = y.id)""",
            window=args.window,
            max_age=args.max_age,
        )
        # The population the whole feature is blocked on: young, in-window, and not yet carded.
        young_uncarded = in_window - young_carded

        print("\n=== universe ===")
        for label, part in (("entities", total), ("has a card", carded), ("has an edge", edged)):
            print(f"  {label:<24} {part:>8,}  {_pct(part, total)}  {_bar(part, total)}")
        print(f"  {'semantic edges':<24} {edges_total:>8,}")

        print(f"\n=== wave candidates (window {args.window}d, max age {args.max_age}d) ===")
        for label, part in (
            ("in window", in_window),
            ("…of those, carded", young_carded),
            ("…of those, edged", young_edged),
        ):
            print(f"  {label:<24} {part:>8,}  {_pct(part, in_window)}  {_bar(part, in_window)}")

        print("\n=== the decision ===")
        print(f"  young + uncarded         {young_uncarded:>8,}   ← the job that unblocks waves")
        if young_uncarded == 0 and in_window == 0:
            print("  → nothing in the window. Check that collect/resolve ran, or widen --window.")
        elif young_uncarded < 500:
            print(
                "  → small. A local model can clear this in one sitting; no budget decision needed."
            )
        else:
            print(
                "  → large enough to be a cost decision. Consider carding only the densest regions"
            )
            print("    first (TAXONOMY_PLAN §2b: embed raw text free, card where it is dense).")

        if young_edged < 4:
            print("\n  Fewer than 4 candidates carry any edge, so no cluster can form at any")
            print(
                "  threshold. This is the linking blocker, not a detector bug (TAXONOMY_PLAN §1)."
            )

        print("\n=== other layers ===")
        for table, note in (
            ("raw_events", "immutable spine"),
            ("entity_community_research", "0 = community layer never run"),
            ("entity_graph_edges", "deterministic spine — independence checks read this"),
            ("wave_clusters", "waves detected so far"),
            ("gate_decisions", ""),
        ):
            try:
                n = _scalar(s, f"SELECT count(*) FROM {table}")  # noqa: S608 — literal table names
            except Exception:  # noqa: BLE001 — a missing table is information, not a crash
                print(f"  {table:<26} {'absent':>8}  (migration not applied?)")
                continue
            print(f"  {table:<26} {n:>8,}  {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
