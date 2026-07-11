"""Pydantic contracts for the two LLM checkpoints (docs 05, 08).

The comprehension card (doc 05 §1) is the structured output of checkpoint 1. It is produced via a
forced tool call whose input schema is *this* model (DR-05.2), so malformed output is an API-level
impossibility, then re-validated here (defense in depth). ``category`` and ``maturity_stage`` are
constrained to the controlled vocabularies so the model can only propose a value the rest of the
system understands; the model's ``category`` is a *proposal* that never silently overwrites the
rule-assigned one (doc 05 §1 — the disagreement is flagged instead).

The impact brief (doc 08 §2) is the structured output of checkpoint 2 — checkpoint 1 says *what an
entity is*, this says *who is economically exposed to it, how, in which direction, and what to
watch*. Same forced-tool-call discipline; ``mechanisms`` is constrained to the closed taxonomy
(idea-spec §7) and ``counter_mechanism`` is a *required* field because a one-sided thesis is
marketing, not intelligence. Beyond the schema the orchestrator runs a post-validation pass (doc 08
§2) the type system can't express: every ticker exposure's revenue line must exist in the loaded
map, and every named mechanism must be legal for the relations of the map surface it touches.

Both contracts live in ``checkpoints/`` so the CI invariant-3 grep has a single home to enforce from.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from seismo.identity.vocab import category_slugs
from seismo.trajectory.ladder import MATURITY_STAGES

Confidence = Literal["low", "med", "high"]
Horizon = Literal["quarters", "1-2y", "3y+"]
_WHAT_IT_IS_MAX_WORDS = 60
_SUMMARY_MAX_WORDS = 200

# The closed mechanism taxonomy (idea-spec §7 / doc 08 §2). A thesis must name ≥1; the impact
# checkpoint may only propose from this set, and the exposure map's ``relation`` types are mapped
# onto it for the mechanism-legality post-validation (``seismo.significance.exposure``).
MECHANISMS: tuple[str, ...] = (
    "substitution",  # a cheaper/better replacement for something people pay for
    "cost_collapse",  # an input cost drops sharply, eroding a margin or moat
    "commoditization",  # a differentiated layer becomes open/standard; value migrates
    "enablement",  # a new capability makes non-viable use cases viable → demand elsewhere
    "dependency_risk",  # an entity becomes load-bearing; its capture/repricing propagates
)


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


# --- Impact brief (doc 08 §2) — LLM checkpoint 2 ----------------------------


class TransmissionStep(BaseModel):
    """One hop of the explicit path entity → capability change → affected revenue line (2–5 steps)."""

    from_node: str
    to_node: str
    effect: str


class Observable(BaseModel):
    """A dated, ideally machine-measurable falsifier (A-7). Prefer ``source='system'`` — something
    the pipeline can itself watch — over ``manual``, so the thesis can be scored later (doc 09)."""

    statement: str  # e.g. "average tokens per active customer over the next two quarters"
    source: Literal["system", "manual"]
    system_metric: str | None = None  # the metric/event it maps to when source='system'
    horizon: Horizon
    direction_if_thesis_holds: Literal["up", "down", "flat"]


class Exposure(BaseModel):
    """One exposed party. ``ticker`` refs must resolve to a company in the loaded map (checked in
    post-validation, doc 08 §2); ``sector_class`` is a free string for private/unlisted actors."""

    kind: Literal["ticker", "sector_class"]
    ref: str  # "NVDA" or a sector-class string like "per-token API revenue models"
    revenue_line: str | None = None  # must exist in the map when kind='ticker'
    direction: Literal["negative", "positive", "ambiguous"]
    magnitude_class: Literal["marginal", "material", "structural"]


class ImpactBrief(BaseModel):
    """The evidence-linked exposure thesis (doc 08 §2). Explains exposure, never predicts prices."""

    entity_ref: str
    mechanisms: list[str] = Field(min_length=1)  # closed taxonomy; ≥1 required
    transmission_path: list[TransmissionStep] = Field(min_length=1)
    exposures: list[Exposure] = Field(min_length=1)
    counter_mechanism: str = Field(min_length=1)  # REQUIRED, stated fairly (idea-spec §7)
    observables: list[Observable] = Field(min_length=1)  # A-7: ≥1 falsifier
    confidence: Confidence
    horizon: Horizon
    summary: str  # <= 200 words, readable (coerced below)
    evidence_refs: list[int] = Field(default_factory=list)

    @field_validator("mechanisms")
    @classmethod
    def _mechanisms_in_taxonomy(cls, v: list[str]) -> list[str]:
        bad = [m for m in v if m not in MECHANISMS]
        if bad:
            raise ValueError(f"mechanism(s) {bad} not in the closed taxonomy {list(MECHANISMS)}")
        return v

    @field_validator("summary")
    @classmethod
    def _cap_summary(cls, v: str) -> str:
        # Coerce rather than reject: the 200-word cap is a display constraint, not worth a retry.
        return " ".join(v.split()[:_SUMMARY_MAX_WORDS])


def brief_tool_schema() -> dict[str, Any]:
    """JSON schema for the forced brief tool call, with the mechanism enum injected on the
    ``mechanisms`` array items (Pydantic emits a bare ``str`` for the runtime-validated field)."""
    schema = ImpactBrief.model_json_schema()
    schema["properties"]["mechanisms"]["items"] = {"type": "string", "enum": list(MECHANISMS)}
    schema["additionalProperties"] = False
    return schema
