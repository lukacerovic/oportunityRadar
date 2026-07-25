"""Pluggable LLM provider (doc 13 A-13) — the *only* module besides ``contracts`` that touches an
LLM, and the only place ``anthropic`` is imported (CI invariant-3 greps for this).

Three providers, one signature (:func:`complete_card`):

* ``mock`` — returns the caller's deterministic ``fallback`` card at $0. Dev + CI run here, so the
  whole comprehension stage is exercised end-to-end without a key or a network (doc 05 amendment).
* ``ollama`` — local model via the REST API with structured-output ``format`` = the tool schema.
  $0, used for plumbing/quality tests on real generations.
* ``anthropic`` — production. Structured output via a **forced tool call** whose input schema is
  the card (doc 05 DR-05.2), so malformed output is an API-level impossibility. Model comes from
  config (``SEISMO_MODEL_LIVE`` live / ``SEISMO_MODEL_HINDCAST`` pinned, doc 13 A-8), never
  hardcoded. Sampling params are omitted — current models reject ``temperature``.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from seismo.config import settings

logger = logging.getLogger(__name__)

CARD_TOOL_NAME = "emit_card"
BRIEF_TOOL_NAME = "emit_brief"
COUNCIL_TOOL_NAME = "emit_verdict"
_MAX_TOKENS = 2048
_BRIEF_MAX_TOKENS = 3072  # the brief schema (transmission path + exposures + observables) is larger
_COUNCIL_MAX_TOKENS = 768  # a verdict is small: stance + confidence + one short argument

# Rough per-MTok (input, output) USD, for cost logging + the budget ceiling only. Confirm against
# the current price sheet at go-live; dev/CI never spends (mock/ollama = $0).
_PRICE_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "opus": (Decimal("5"), Decimal("25")),
    "sonnet": (Decimal("3"), Decimal("15")),
    "haiku": (Decimal("1"), Decimal("5")),
}


@dataclass
class LLMResult:
    content: dict[str, Any]
    model: str
    cost_usd: Decimal
    input_tokens: int = 0
    output_tokens: int = 0


def complete_card(
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    fallback: dict[str, Any],
    purpose: str = "live",
) -> LLMResult:
    """Produce a comprehension card as structured JSON. ``fallback`` is the deterministic card the
    ``mock`` provider returns verbatim (and the shape real providers must match)."""
    return _complete(
        system,
        user,
        schema,
        fallback=fallback,
        purpose=purpose,
        tool_name=CARD_TOOL_NAME,
        tool_description="Return the comprehension card for this entity.",
        max_tokens=_MAX_TOKENS,
    )


def complete_brief(
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    fallback: dict[str, Any],
    purpose: str = "live",
) -> LLMResult:
    """Produce an impact brief as structured JSON (doc 08 checkpoint 2). Same forced-tool-call
    discipline as :func:`complete_card`; ``fallback`` is the deterministic draft the ``mock``
    provider returns verbatim."""
    return _complete(
        system,
        user,
        schema,
        fallback=fallback,
        purpose=purpose,
        tool_name=BRIEF_TOOL_NAME,
        tool_description="Return the impact brief for this entity.",
        max_tokens=_BRIEF_MAX_TOKENS,
    )


def complete_council(
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    fallback: dict[str, Any],
    purpose: str = "live",
) -> LLMResult:
    """Produce one council verdict as structured JSON (doc 08 §5). Same forced-tool-call
    discipline as :func:`complete_brief`; ``fallback`` is the deterministic verdict the ``mock``
    provider returns verbatim (a neutral ``watch`` stance — mock never asserts an unfounded
    judgement)."""
    return _complete(
        system,
        user,
        schema,
        fallback=fallback,
        purpose=purpose,
        tool_name=COUNCIL_TOOL_NAME,
        tool_description="Return this council member's verdict on the impact brief.",
        max_tokens=_COUNCIL_MAX_TOKENS,
    )


def _complete(
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    fallback: dict[str, Any],
    purpose: str,
    tool_name: str,
    tool_description: str,
    max_tokens: int,
) -> LLMResult:
    provider = settings.llm_provider
    if provider == "mock":
        return LLMResult(content=fallback, model="mock", cost_usd=Decimal(0))
    if provider == "ollama":
        return _ollama(system, user, schema, max_tokens)
    if provider == "anthropic":
        return _anthropic(system, user, schema, tool_name, tool_description, max_tokens, purpose)
    if provider == "claude_cli":
        # The card/brief `schema` is a plain JSON schema, so it maps 1:1 onto the CLI's
        # ``--json-schema`` structured-output flag (unlike Anthropic's forced-tool input_schema
        # wrapper). Fail-closed: on any CLI failure ``_claude_cli`` returns None and we hand back
        # the caller's deterministic ``fallback`` card, so this path never raises.
        result = _claude_cli(f"{system}\n\n{user}", schema)
        return LLMResult(
            content=result if result is not None else fallback,
            # A failed CLI call must not carry the same model tag as a real generation (doc 13 —
            # this exact ambiguity produced a mislabeled comprehension-card version once already).
            model=(
                f"claude_cli:{settings.claude_cli_model}"
                if result is not None
                else "claude_cli:fallback"
            ),
            # cost_usd=0: CLI-session usage isn't metered per-token on this path, so we don't
            # fabricate an estimate. Not a real free lunch — just not separately billed here.
            cost_usd=Decimal(0),
        )
    raise ValueError(f"unknown LLM provider {provider!r}")


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    tier = next((k for k in _PRICE_PER_MTOK if k in model), "sonnet")
    price_in, price_out = _PRICE_PER_MTOK[tier]
    return (Decimal(input_tokens) * price_in + Decimal(output_tokens) * price_out) / Decimal(
        1_000_000
    )


def _ollama(system: str, user: str, schema: dict[str, Any], max_tokens: int) -> LLMResult:
    import httpx

    model = settings.ollama_model
    resp = httpx.post(
        f"{settings.ollama_host}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,  # ollama structured outputs: constrain to the JSON schema
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": max_tokens},
        },
        timeout=300.0,
    )
    resp.raise_for_status()
    data = resp.json()
    content = json.loads(data["message"]["content"])
    return LLMResult(
        content=content,
        model=f"ollama:{model}",
        cost_usd=Decimal(0),
        input_tokens=int(data.get("prompt_eval_count") or 0),
        output_tokens=int(data.get("eval_count") or 0),
    )


def _anthropic(
    system: str,
    user: str,
    schema: dict[str, Any],
    tool_name: str,
    tool_description: str,
    max_tokens: int,
    purpose: str,
) -> LLMResult:
    import anthropic

    model = settings.model_hindcast if purpose == "hindcast" else settings.model_live
    if not model:
        raise RuntimeError(
            "anthropic provider needs SEISMO_MODEL_LIVE (or SEISMO_MODEL_HINDCAST) set to a "
            "Sonnet-class snapshot id (doc 05 DR-05.1 / A-8)"
        )
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        tools=[
            {
                "name": tool_name,
                "description": tool_description,
                "input_schema": schema,
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user}],
    )
    block = next(b for b in message.content if b.type == "tool_use")
    return LLMResult(
        content=dict(block.input),
        model=model,
        cost_usd=estimate_cost(model, message.usage.input_tokens, message.usage.output_tokens),
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
    )


def _claude_cli(
    prompt: str, schema: dict[str, Any], *, timeout_s: int | None = None
) -> dict[str, Any] | None:
    """Shell out to the installed ``claude`` CLI in non-interactive print mode with a JSON schema,
    returning the parsed structured result as a dict, or ``None`` on *any* failure.

    Verified against the installed CLI: ``-p/--print`` (non-interactive), ``--bare`` (skip hooks/
    plugins/CLAUDE.md discovery), ``--model`` (alias override), ``--output-format json`` (wraps the
    reply in a single JSON result object), and ``--json-schema`` (constrain structured output) are
    all real flags. The wrapper object carries the answer in its ``result`` field (and signals
    failures via ``is_error``); ``result`` may be a dict or a JSON-encoded string.

    Fail-closed by contract: subprocess timeout, non-zero exit, unparseable JSON, an ``is_error``
    wrapper, or a missing/misshapen result all log a warning and return ``None`` — never raise.
    """
    timeout = settings.claude_cli_timeout_s if timeout_s is None else timeout_s
    cmd = [
        settings.claude_cli_bin,
        "-p",
        "--bare",
        "--model",
        settings.claude_cli_model,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
        prompt,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("claude_cli: timed out after %ss", timeout)
        return None
    except OSError as exc:  # binary missing / not executable
        logger.warning("claude_cli: could not launch %r (%s)", settings.claude_cli_bin, exc)
        return None

    if proc.returncode != 0:
        logger.warning(
            "claude_cli: exit %d — %s", proc.returncode, (proc.stderr or "").strip()[:500]
        )
        return None

    try:
        wrapper = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("claude_cli: stdout was not JSON (%s)", exc)
        return None

    try:
        if wrapper.get("is_error"):
            logger.warning("claude_cli: CLI reported an error — %s", wrapper.get("result"))
            return None
        result = wrapper["result"]
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict):
            raise TypeError(f"expected dict result, got {type(result).__name__}")
        return result
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("claude_cli: could not extract structured result (%s)", exc)
        return None


def complete_triage(facts: dict[str, Any]) -> dict[str, Any] | None:
    """Decide whether an entity described by ``facts`` is worth tracking.

    Returns a plain ``dict`` (``{"decision": "track"|"skip", "sector": ...}``) — intentionally *not*
    an :class:`LLMResult`, since triage has no per-token accounting — or ``None`` to signal the
    caller to fall back to its own deterministic logic.

    * ``mock`` → ``None`` immediately (the mock provider is $0 / no network by contract).
    * ``claude_cli`` → constrained structured call via :func:`_claude_cli` (``None`` on failure).
    * anything else (``ollama``, ``anthropic``) → ``None`` for now.
    """
    provider = settings.llm_provider
    if provider == "mock":
        return None
    if provider == "claude_cli":
        schema = {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": ["track", "skip"]},
                "sector": {"type": "string"},
            },
            "required": ["decision"],
        }
        prompt = (
            "You are triaging entities for a technology-signal radar. Decide whether the entity "
            "described by the following facts is worth tracking. Answer with decision='track' if "
            "it is a substantive, real, on-topic entity worth monitoring, otherwise 'skip'. "
            "Include a short lowercase 'sector' label when you can.\n\n"
            f"facts: {json.dumps(facts, separators=(',', ':'), default=str)}"
        )
        return _claude_cli(prompt, schema)
    # TODO(step >1): wire ollama / anthropic triage backends; out of scope for this port.
    return None
