"""Config loads with safe defaults; env prefix works."""

from __future__ import annotations

from seismo.config import Settings


def test_defaults_are_dev_safe() -> None:
    s = Settings()
    assert s.product_name == "Seismograph"
    assert s.llm_provider == "mock"  # dev/CI default costs $0
    assert s.breakout_min_breadth == 2  # doc 13 A-5 (3 evidence types live)
    assert s.cohort_min_size == 8


def test_env_prefix_overrides(monkeypatch) -> None:
    monkeypatch.setenv("SEISMO_PRODUCT_NAME", "Foreshock")
    monkeypatch.setenv("SEISMO_BREAKOUT_MIN_BREADTH", "3")
    s = Settings()
    assert s.product_name == "Foreshock"
    assert s.breakout_min_breadth == 3
