"""Hindcast case definitions (doc 11 §2) — the pinned, executable assertions.

A case is a YAML file: a window, the seeds its loaders must cover, an optional pinned brief target,
and a list of *structured* assertions. The assertions check **schema-level facts** — an entity id
resolves, a momentum tier is reached, a gate decision is made, a brief field is present — never a
string match on prose (doc 11 §2). LLM checkpoints are stochastic; asserting on their prose would
make CI flap, so every assertion here is deterministic given the pipeline's structured outputs.

This module only parses and validates the case. Evaluation lives in
:mod:`seismo.hindcast.assertions` and orchestration in :mod:`seismo.hindcast.runner`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# The assertion types the evaluators understand (doc 11 §2). Kept closed so an unknown ``type`` in
# a case file is a load-time error, not a silent skip at evaluation time.
ASSERTION_TYPES: frozenset[str] = frozenset(
    {"identity", "momentum", "gate", "brief", "brief_absent"}
)

CASES_DIR = Path(__file__).resolve().parents[3] / "hindcast" / "cases"


class Window(BaseModel):
    model_config = ConfigDict(frozen=True)
    from_: date = Field(alias="from")
    to: date

    @field_validator("to")
    @classmethod
    def _to_after_from(cls, v: date, info) -> date:  # type: ignore[no-untyped-def]
        frm = info.data.get("from_")
        if frm is not None and v < frm:
            raise ValueError("window 'to' precedes 'from'")
        return v


class Seeds(BaseModel):
    """What the loaders must cover for the case (doc 11 §1). Every field optional — a case may only
    need GitHub star history, or only an HN spike."""

    model_config = ConfigDict(frozen=True)
    github: list[str] = Field(default_factory=list)
    arxiv: list[str] = Field(default_factory=list)
    hf_orgs: list[str] = Field(default_factory=list)
    wayback: list[str] = Field(default_factory=list)
    pypi: list[str] = Field(default_factory=list)


class BriefTarget(BaseModel):
    """The pinned H2 brief (doc 11 §2). ``entity`` is an anchor ref (``registry:native_id``) the
    runner force-briefs at ``as_of``. Absent on brief-free negative cases (Reflection-70B)."""

    model_config = ConfigDict(frozen=True)
    as_of: date
    entity: str


class Assertion(BaseModel):
    """One pinned check. ``id``/``type`` are fixed; the remaining fields are the type's parameters,
    kept in ``params`` so each evaluator reads exactly what it needs (doc 11 §2)."""

    model_config = ConfigDict(extra="allow")
    id: str
    type: str

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in ASSERTION_TYPES:
            raise ValueError(f"unknown assertion type {v!r}; known: {sorted(ASSERTION_TYPES)}")
        return v

    @property
    def params(self) -> dict[str, object]:
        """Everything except ``id``/``type`` — the evaluator's parameters."""
        return {k: v for k, v in (self.__pydantic_extra__ or {}).items()}


class Case(BaseModel):
    model_config = ConfigDict(frozen=True)
    case: str
    window: Window
    seeds: Seeds = Field(default_factory=Seeds)
    brief: BriefTarget | None = None
    assertions: list[Assertion] = Field(min_length=1)

    @property
    def name(self) -> str:
        return self.case


def load_case(path: str | Path) -> Case:
    """Parse and validate a single case YAML file."""
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return Case.model_validate(raw)


def load_case_by_name(name: str, cases_dir: Path | None = None) -> Case:
    """Resolve ``<cases_dir>/<name>.yaml`` and load it. Raises ``FileNotFoundError`` if missing."""
    directory = cases_dir or CASES_DIR
    path = directory / f"{name}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in directory.glob("*.yaml")) if directory.exists() else []
        raise FileNotFoundError(f"no hindcast case {name!r} in {directory} (have: {available})")
    return load_case(path)
