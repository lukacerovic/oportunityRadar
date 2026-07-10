"""Invariant 3 (doc 02 §1, doc 13 A-13): no LLM SDK imported outside checkpoints/."""

from __future__ import annotations

import re
from pathlib import Path

_LLM_IMPORT = re.compile(r"^\s*(?:import|from)\s+(anthropic|ollama)\b", re.MULTILINE)
_SRC = Path(__file__).resolve().parents[1] / "src" / "seismo"


def test_no_llm_sdk_import_outside_checkpoints() -> None:
    offenders = [
        str(p.relative_to(_SRC))
        for p in _SRC.rglob("*.py")
        if "checkpoints" not in p.parts and _LLM_IMPORT.search(p.read_text())
    ]
    assert not offenders, f"LLM SDK imported outside checkpoints/: {offenders}"
