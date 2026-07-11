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
