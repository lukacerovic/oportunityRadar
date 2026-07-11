"""Pydantic contracts for the two LLM checkpoints (docs 05, 08).

The comprehension card (doc 05 §1) is the structured output of checkpoint 1. It is produced via a
forced tool call whose input schema is *this* model (DR-05.2), so malformed output is an API-level
impossibility, then re-validated here (defense in depth). ``category`` and ``maturity_stage`` are
constrained to the controlled vocabularies so the model can only propose a value the rest of the
system understands; the model's ``category`` is a *proposal* that never silently overwrites the
rule-assigned one (doc 05 §1 — the disagreement is flagged instead).

Stage 7 (impact) adds its own contract here later. Kept in ``checkpoints/`` so the CI invariant-3
grep has a single home to enforce from.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from seismo.identity.vocab import category_slugs
from seismo.trajectory.ladder import MATURITY_STAGES

Confidence = Literal["low", "med", "high"]
_WHAT_IT_IS_MAX_WORDS = 60


class ComprehensionCard(BaseModel):
    """Structured claims about one entity, grounded only in its evidence pack (doc 05 §1)."""

    entity_ref: str
    what_it_is: str  # <= 60 words, plain language (coerced below)
    category: str  # controlled vocabulary (a proposal; never overwrites the rule category)
    function: str  # what it does, mechanically
    claimed_advantage: str  # the pitch, attributed as a claim
    replaces_or_enables: list[str] = Field(default_factory=list)
    maturity_stage: str  # ladder stage per visible evidence
    who_is_behind: str  # org/individuals, affiliation if visible
    open_questions: list[str] = Field(default_factory=list)  # what the evidence does NOT establish
    evidence_refs: list[int] = Field(default_factory=list)  # raw_event ids relied on
    confidence: Confidence

    @field_validator("category")
    @classmethod
    def _category_in_vocab(cls, v: str) -> str:
        if v not in category_slugs():
            raise ValueError(f"category {v!r} not in controlled vocabulary")
        return v

    @field_validator("maturity_stage")
    @classmethod
    def _maturity_in_ladder(cls, v: str) -> str:
        if v not in MATURITY_STAGES:
            raise ValueError(f"maturity_stage {v!r} not on the ladder")
        return v

    @field_validator("what_it_is")
    @classmethod
    def _cap_words(cls, v: str) -> str:
        # Coerce rather than reject: the 60-word cap is a display constraint, not worth a retry.
        words = v.split()
        return " ".join(words[:_WHAT_IT_IS_MAX_WORDS])


def card_tool_schema() -> dict[str, Any]:
    """JSON schema for the forced tool call, with the controlled-vocabulary enums injected (Pydantic
    doesn't emit them for the plain ``str`` fields that carry runtime validators)."""
    schema = ComprehensionCard.model_json_schema()
    schema["properties"]["category"]["enum"] = list(category_slugs())
    schema["properties"]["maturity_stage"]["enum"] = list(MATURITY_STAGES)
    schema["additionalProperties"] = False
    return schema
