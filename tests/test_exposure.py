"""Exposure-map loader (doc 08 §1, doc 13 A-1) — schema validation, reach_link derivation, and the
authoritative DB rebuild. Parsing tests are pure; load tests run against real Postgres (rolled
back), including the real company files in ``exposure_map/`` (the curated 30-company roster)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.significance.exposure import (
    ExposureCompanyDoc,
    derive_reach_links,
    load_map,
    parse_company_file,
)

REPO_MAP_DIR = Path(__file__).resolve().parent.parent / "exposure_map"


def _doc(**over) -> dict:  # noqa: ANN003
    base = {
        "ticker": "tst",
        "name": "Test Co",
        "sector": "software",
        "updated": "2026-07-01",
        "revenue_lines": [
            {
                "id": "cloud",
                "name": "Cloud",
                "share_of_revenue": 0.6,
                "source": "10-K FY2025",
                "threat_surface": [
                    {"category": "inference-runtime", "relation": "demand_risk", "core": True},
                    {"category": "model-foundation", "relation": "dependency_risk"},
                ],
            }
        ],
    }
    base.update(over)
    return base


# --- parsing + derivation ---------------------------------------------------


def test_valid_doc_parses_and_uppercases_ticker() -> None:
    doc = ExposureCompanyDoc.model_validate(_doc())
    assert doc.ticker == "TST"  # normalized upper
    links = derive_reach_links(doc)
    keys = {(lk.category, lk.relation, lk.core) for lk in links}
    assert keys == {
        ("inference-runtime", "demand_risk", True),
        ("model-foundation", "dependency_risk", False),
    }
    assert all(lk.ticker == "TST" and lk.revenue_line == "cloud" for lk in links)


def test_core_is_ored_across_duplicate_edges() -> None:
    # Same (category, revenue_line, relation) appearing core + non-core collapses to one core=True.
    doc = ExposureCompanyDoc.model_validate(
        _doc(
            revenue_lines=[
                {
                    "id": "cloud",
                    "name": "Cloud",
                    "share_of_revenue": 0.5,
                    "source": "s",
                    "threat_surface": [
                        {"category": "vector-db", "relation": "substitution_partial"},
                        {"category": "vector-db", "relation": "substitution_partial", "core": True},
                    ],
                }
            ]
        )
    )
    links = derive_reach_links(doc)
    assert len(links) == 1 and links[0].core is True


def test_rejects_share_sum_over_ceiling() -> None:
    bad = _doc(
        revenue_lines=[
            {"id": "a", "name": "A", "share_of_revenue": 0.7, "source": "s"},
            {"id": "b", "name": "B", "share_of_revenue": 0.5, "source": "s"},
        ]
    )
    with pytest.raises(ValidationError, match="shares sum"):
        ExposureCompanyDoc.model_validate(bad)


def test_rejects_unknown_category() -> None:
    bad = _doc()
    bad["revenue_lines"][0]["threat_surface"][0]["category"] = "not-a-real-category"
    with pytest.raises(ValidationError, match="category"):
        ExposureCompanyDoc.model_validate(bad)


def test_rejects_unknown_relation() -> None:
    bad = _doc()
    bad["revenue_lines"][0]["threat_surface"][0]["relation"] = "vibes"
    with pytest.raises(ValidationError, match="relation"):
        ExposureCompanyDoc.model_validate(bad)


def test_rejects_missing_source() -> None:
    bad = _doc()
    bad["revenue_lines"][0]["source"] = ""
    with pytest.raises(ValidationError):
        ExposureCompanyDoc.model_validate(bad)


# --- real repo files load -----------------------------------------------------


def test_all_real_map_files_are_valid() -> None:
    files = sorted(REPO_MAP_DIR.glob("*.yaml"))
    assert len(files) >= 8, "the minimal 8-company slice should be present"
    for f in files:
        parse_company_file(f)  # raises on any invalid file


def test_load_map_populates_and_is_idempotent(clean_db: Session) -> None:
    expected = len(sorted(REPO_MAP_DIR.glob("*.yaml")))  # one company per file (future-proof)
    first = load_map(clean_db, REPO_MAP_DIR)
    clean_db.flush()
    assert first.errors == []
    assert first.companies == expected
    assert first.reach_links > 0
    companies = clean_db.execute(text("SELECT COUNT(*) FROM exposure_companies")).scalar_one()
    links = clean_db.execute(text("SELECT COUNT(*) FROM reach_links")).scalar_one()
    assert companies == expected

    second = load_map(clean_db, REPO_MAP_DIR)  # re-load = same shape, no growth
    clean_db.flush()
    n_companies = clean_db.execute(text("SELECT COUNT(*) FROM exposure_companies")).scalar_one()
    assert n_companies == expected
    assert clean_db.execute(text("SELECT COUNT(*) FROM reach_links")).scalar_one() == links
    assert second.reach_links == first.reach_links


def test_load_map_is_authoritative(clean_db: Session, tmp_path: Path) -> None:
    # Dropping a threat surface in YAML must shrink reach_links to match (YAML is the truth).
    p = tmp_path / "TST.yaml"
    import yaml

    p.write_text(yaml.safe_dump(_doc()))
    load_map(clean_db, tmp_path)
    clean_db.flush()
    assert (
        clean_db.execute(text("SELECT COUNT(*) FROM reach_links WHERE ticker='TST'")).scalar_one()
        == 2
    )

    dropped = _doc()
    dropped["revenue_lines"][0]["threat_surface"] = [
        {"category": "inference-runtime", "relation": "demand_risk"}
    ]
    p.write_text(yaml.safe_dump(dropped))
    load_map(clean_db, tmp_path)
    clean_db.flush()
    rows = (
        clean_db.execute(text("SELECT category FROM reach_links WHERE ticker='TST'"))
        .scalars()
        .all()
    )
    assert rows == ["inference-runtime"], "removing a threat in YAML removes its reach_link"
