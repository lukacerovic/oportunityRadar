"""Exposure map — YAML-in-git loaded into Postgres (doc 08 DR-08.1, doc 13 A-1).

The exposure map is the compounding asset: a hand-curated, version-controlled description of which
public companies are exposed to which technology *categories*, through which revenue line, in which
direction. It is the surface the significance gate (doc 07) tests entities against and the surface
the impact checkpoint (doc 08) reasons over — both read the *same* curated linkage, so they can
never disagree about what "touches the map" means.

``exposure_map/*.yaml`` is the source of truth (one file per company). :func:`load_map` validates
each file (this module's Pydantic models + the category-vocab cross-check) and upserts into
``exposure_companies`` (the full doc as JSONB) + ``reach_links`` (the derived category→ticker index
the gate joins on). Loading is idempotent and authoritative: a company's ``reach_links`` are fully
rebuilt from its current ``threat_surface`` on every load, so deleting a threat entry in YAML
removes the row. Nothing here fetches or reasons — it is a validating loader (invariant 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.identity.vocab import category_slugs

# How a technology category threatens (or aids) a revenue line. Kept small + controlled; the impact
# checkpoint (doc 08 §2) maps these to the legal mechanism taxonomy. Extend deliberately.
RELATIONS = frozenset(
    {
        "demand_risk",  # cheaper/more-efficient tech shrinks unit demand (e.g. GPUs per capability)
        "substitution_partial",  # an alternative erodes some of the line
        "substitution_full",  # an alternative can wholly replace the line
        "commoditization",  # margins compress as the capability becomes a commodity
        "cost_collapse",  # the input cost of the line collapses
        "enablement",  # the tech grows the line (positive exposure)
        "dependency_risk",  # the line depends on the tech; disruption there flows through
        "margin_pressure",  # pricing/competition pressure on the line
    }
)

SHARE_SUM_CEILING = 1.05  # doc 08 §1: revenue shares may sum slightly >1 (overlap), never far

# Which impact mechanisms (idea-spec §7, ``contracts.MECHANISMS``) a map ``relation`` can legally
# manifest as. The impact checkpoint's mechanism-legality post-validation (doc 08 §2) requires every
# mechanism a brief names to be permitted by at least one relation on the map surface the entity's
# category touches — a guardrail against a brief inventing a transmission unrelated to any mapped
# edge (e.g. claiming ``enablement`` when the only surface it touches is a substitution relation).
RELATION_MECHANISMS: dict[str, frozenset[str]] = {
    # efficiency shrinks unit demand — driven by a cheaper substitute, an input-cost collapse, or
    # the capability becoming a commodity (the DeepSeek-vs-GPU-demand surface is a demand_risk edge).
    "demand_risk": frozenset({"substitution", "cost_collapse", "commoditization"}),
    "substitution_partial": frozenset({"substitution", "commoditization"}),
    "substitution_full": frozenset({"substitution", "commoditization"}),
    "commoditization": frozenset({"commoditization", "cost_collapse"}),
    "cost_collapse": frozenset({"cost_collapse", "commoditization"}),
    "enablement": frozenset({"enablement"}),
    "dependency_risk": frozenset({"dependency_risk"}),
    "margin_pressure": frozenset({"commoditization", "substitution", "cost_collapse"}),
}


class ThreatSurface(BaseModel):
    """One (category → revenue line) exposure edge — the atom a ``reach_link`` derives from."""

    category: str
    relation: str
    core: bool = False

    @field_validator("category")
    @classmethod
    def _category_in_vocab(cls, v: str) -> str:
        if v not in category_slugs():
            raise ValueError(f"threat_surface category {v!r} not in the category vocabulary")
        return v

    @field_validator("relation")
    @classmethod
    def _relation_known(cls, v: str) -> str:
        if v not in RELATIONS:
            raise ValueError(f"relation {v!r} not in {sorted(RELATIONS)}")
        return v


class RevenueLine(BaseModel):
    id: str
    name: str
    share_of_revenue: float = Field(ge=0.0, le=1.0)
    source: str = Field(min_length=1)  # doc 08 DR-08.3: every line is sourced (auditable)
    depends_on: list[str] = Field(default_factory=list)
    threat_surface: list[ThreatSurface] = Field(default_factory=list)


class ExposureCompanyDoc(BaseModel):
    """A validated company file. Serialized verbatim into ``exposure_companies.doc`` (JSONB)."""

    ticker: str
    name: str
    cik: str | None = None
    sector: str
    revenue_lines: list[RevenueLine] = Field(min_length=1)
    moat_notes: str | None = None
    sensitivity_notes: str | None = None
    updated: date

    @field_validator("ticker")
    @classmethod
    def _ticker_upper(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def _shares_sane(self) -> ExposureCompanyDoc:
        total = sum(line.share_of_revenue for line in self.revenue_lines)
        if total > SHARE_SUM_CEILING:
            raise ValueError(
                f"{self.ticker}: revenue shares sum to {total:.2f} > {SHARE_SUM_CEILING}"
            )
        ids = [line.id for line in self.revenue_lines]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.ticker}: duplicate revenue_line id")
        return self


@dataclass
class DerivedReachLink:
    category: str
    ticker: str
    revenue_line: str
    relation: str
    core: bool


def derive_reach_links(doc: ExposureCompanyDoc) -> list[DerivedReachLink]:
    """The category→ticker index the gate reads (doc 07 §2): one row per threat_surface entry.

    Deduped on the (category, ticker, revenue_line, relation) key; ``core`` is OR-ed so a line
    flagged core anywhere wins."""
    out: dict[tuple[str, str, str, str], DerivedReachLink] = {}
    for line in doc.revenue_lines:
        for ts in line.threat_surface:
            key = (ts.category, doc.ticker, line.id, ts.relation)
            existing = out.get(key)
            if existing is None:
                out[key] = DerivedReachLink(ts.category, doc.ticker, line.id, ts.relation, ts.core)
            elif ts.core:
                existing.core = True
    return list(out.values())


@dataclass
class RevenueLineSlice:
    """One revenue line of an exposed company, with only the threat entries matching the entity's
    category kept — the pre-selected surface the impact checkpoint reasons over (doc 08 §3)."""

    id: str
    name: str
    share_of_revenue: float
    source: str
    threats: list[tuple[str, bool]]  # (relation, core) for the matching category only


@dataclass
class CompanySlice:
    ticker: str
    name: str
    sector: str
    moat_notes: str | None
    sensitivity_notes: str | None
    lines: list[RevenueLineSlice]  # only lines whose threat_surface touches the category


@dataclass
class CategoryReach:
    """Everything the impact layer needs about how one category touches the map: the company slices
    to put in the pack, the mechanisms the touched relations legally permit, and the (ticker →
    revenue-line-ids) index the brief's ticker exposures are post-validated against (doc 08 §2)."""

    category: str
    slices: list[CompanySlice]
    allowed_mechanisms: frozenset[str]
    valid_lines: dict[str, set[str]]  # ticker → every revenue_line id that ticker has in the map

    @property
    def is_empty(self) -> bool:
        return not self.slices


def category_reach(session: Session, category: str | None) -> CategoryReach:
    """Assemble the map slices a given category touches (via ``reach_links``) plus the derived
    mechanism-legality set and per-ticker revenue-line index. Pure read; returns an empty reach when
    the category is unmapped (the gate hard-excludes those before a brief is ever requested, A-6)."""
    empty = CategoryReach(category or "", [], frozenset(), {})
    if not category:
        return empty
    links = session.execute(
        text(
            "SELECT ticker, revenue_line, relation, core FROM reach_links WHERE category = :c "
            "ORDER BY ticker, revenue_line"
        ),
        {"c": category},
    ).mappings().all()
    if not links:
        return empty

    tickers = sorted({row["ticker"] for row in links})
    docs = {
        row["ticker"]: row["doc"]
        for row in session.execute(
            text("SELECT ticker, doc FROM exposure_companies WHERE ticker = ANY(:t)"),
            {"t": tickers},
        ).mappings()
    }

    # (ticker, line) → [(relation, core)] for the matching category only.
    by_line: dict[tuple[str, str], list[tuple[str, bool]]] = {}
    relations: set[str] = set()
    for row in links:
        by_line.setdefault((row["ticker"], row["revenue_line"]), []).append(
            (row["relation"], bool(row["core"]))
        )
        relations.add(row["relation"])

    slices: list[CompanySlice] = []
    valid_lines: dict[str, set[str]] = {}
    for ticker in tickers:
        doc = docs.get(ticker) or {}
        all_lines = {ln["id"] for ln in doc.get("revenue_lines", [])}
        valid_lines[ticker] = all_lines
        line_index = {ln["id"]: ln for ln in doc.get("revenue_lines", [])}
        line_slices: list[RevenueLineSlice] = []
        for (t, line_id), threats in by_line.items():
            if t != ticker:
                continue
            ln = line_index.get(line_id, {})
            line_slices.append(
                RevenueLineSlice(
                    id=line_id,
                    name=ln.get("name", line_id),
                    share_of_revenue=float(ln.get("share_of_revenue", 0.0)),
                    source=ln.get("source", ""),
                    threats=sorted(threats),
                )
            )
        line_slices.sort(key=lambda s: (-s.share_of_revenue, s.id))
        slices.append(
            CompanySlice(
                ticker=ticker,
                name=doc.get("name", ticker),
                sector=doc.get("sector", ""),
                moat_notes=doc.get("moat_notes"),
                sensitivity_notes=doc.get("sensitivity_notes"),
                lines=line_slices,
            )
        )

    allowed = frozenset().union(*(RELATION_MECHANISMS.get(r, frozenset()) for r in relations))
    return CategoryReach(category, slices, allowed, valid_lines)


@dataclass
class LoadStats:
    companies: int = 0
    revenue_lines: int = 0
    reach_links: int = 0
    categories_covered: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    def as_note(self) -> str:
        cov = f"{self.categories_covered} categories covered"
        errs = f" — {len(self.errors)} FILE ERROR(S)" if self.errors else ""
        return (
            f"companies={self.companies} revenue_lines={self.revenue_lines} "
            f"reach_links={self.reach_links} ({cov}){errs}"
        )


def parse_company_file(path: Path) -> ExposureCompanyDoc:
    """Read + validate one company YAML. Raises ``ValidationError``/``ValueError`` on bad input."""
    raw = yaml.safe_load(path.read_text()) or {}
    return ExposureCompanyDoc.model_validate(raw)


def load_map(session: Session, map_dir: str | Path = "exposure_map") -> LoadStats:
    """Validate every ``*.yaml`` under ``map_dir`` and upsert companies + rebuild their reach_links.

    A single bad file is isolated (recorded in ``stats.errors``) so one typo doesn't block the rest;
    the caller decides whether a non-empty error list is fatal. Authoritative per company: a
    company's reach_links are deleted and re-derived, so YAML is the sole source of truth."""
    stats = LoadStats()
    now = datetime.now(UTC)
    covered: set[str] = set()

    for path in sorted(Path(map_dir).glob("*.yaml")):
        try:
            doc = parse_company_file(path)
        except (ValidationError, ValueError, yaml.YAMLError) as exc:
            stats.errors.append(f"{path.name}: {exc}")
            continue

        session.execute(
            text(
                """
                INSERT INTO exposure_companies (ticker, name, sector, doc, loaded_at)
                VALUES (:t, :n, :s, CAST(:d AS JSONB), :at)
                ON CONFLICT (ticker) DO UPDATE
                  SET name = EXCLUDED.name, sector = EXCLUDED.sector,
                      doc = EXCLUDED.doc, loaded_at = EXCLUDED.loaded_at
                """
            ),
            {
                "t": doc.ticker,
                "n": doc.name,
                "s": doc.sector,
                "d": _json(doc.model_dump(mode="json")),
                "at": now,
            },
        )
        # Authoritative rebuild: drop this ticker's links, then insert the current derivation.
        session.execute(text("DELETE FROM reach_links WHERE ticker = :t"), {"t": doc.ticker})
        links = derive_reach_links(doc)
        for link in links:
            session.execute(
                text(
                    """
                    INSERT INTO reach_links (category, ticker, revenue_line, relation, core)
                    VALUES (:c, :t, :rl, :r, :core)
                    ON CONFLICT (category, ticker, revenue_line, relation)
                      DO UPDATE SET core = EXCLUDED.core
                    """
                ),
                {
                    "c": link.category,
                    "t": link.ticker,
                    "rl": link.revenue_line,
                    "r": link.relation,
                    "core": link.core,
                },
            )
            covered.add(link.category)

        stats.companies += 1
        stats.revenue_lines += len(doc.revenue_lines)
        stats.reach_links += len(links)

    stats.categories_covered = len(covered)
    return stats


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, default=str)
