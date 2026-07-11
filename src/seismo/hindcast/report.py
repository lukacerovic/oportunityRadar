"""Markdown trace report for a hindcast run (doc 11 §4).

The report is the PMG-demo-grade artifact: the pass/fail verdict, each assertion's detail line, any
loader gaps, and the per-day momentum-state trace of the case entity — the shape of the foreshock
the system did (or didn't) see, day by day.
"""

from __future__ import annotations

from datetime import date, datetime

from seismo.hindcast.assertions import AssertionResult
from seismo.hindcast.case import Case


def render_report(
    case: Case,
    results: list[AssertionResult],
    *,
    warnings: list[str],
    trace: list[tuple[date, str, float | None]],
    trace_label: str | None,
    brief_as_of: datetime | None,
) -> str:
    total = len(results)
    failed = sum(1 for r in results if not r.passed)
    verdict = "PASS" if failed == 0 else "FAIL"
    lines: list[str] = []
    lines.append(f"# Hindcast — {case.name} — {verdict}")
    lines.append("")
    lines.append(
        f"Window `{case.window.from_}`..`{case.window.to}` · "
        f"{total - failed}/{total} assertions green"
        + (f" · brief pinned at `{brief_as_of.date()}`" if brief_as_of else "")
    )
    lines.append("")

    lines.append("## Assertions")
    lines.append("")
    lines.append("| id | type | result | detail |")
    lines.append("|---|---|---|---|")
    for r in results:
        mark = "✅" if r.passed else "❌"
        detail = r.detail.replace("|", "\\|")
        lines.append(f"| {r.id} | {r.type} | {mark} | {detail} |")
    lines.append("")

    if warnings:
        lines.append("## Loader notes")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    if trace:
        lines.append(f"## Momentum trace — {trace_label or 'case entity'}")
        lines.append("")
        lines.append("| day | state | score |")
        lines.append("|---|---|---|")
        for d, state, score in trace:
            s = "" if score is None else f"{score:.3f}"
            lines.append(f"| {d} | {state} | {s} |")
        lines.append("")

    return "\n".join(lines)
