"""Pluggable LLM provider (doc 13 A-13) — the *only* module besides ``contracts`` that touches an
LLM, and the only place ``anthropic`` is imported (CI invariant-3 greps for this).

Four providers, one signature (:func:`complete_card`):

* ``mock`` — returns the caller's deterministic ``fallback`` card at $0. Dev + CI run here, so the
  whole comprehension stage is exercised end-to-end without a key or a network (doc 05 amendment).
* ``ollama`` — local model via the REST API with structured-output ``format`` = the tool schema.
  $0, used for plumbing/quality tests on real generations.
* ``claude_cli`` — headless ``claude -p``, billed to the Claude Code subscription rather than to
  API credit. Schema is prompted for rather than forced, and each call carries Claude Code's own
  scaffolding (~24k tokens), so it costs ~10x the API for the same work — see :func:`_claude_cli`.
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
SANITY_TOOL_NAME = "emit_sanity_batch"
COMMUNITY_TOOL_NAME = "emit_community_verdict"
EXPLAIN_TOOL_NAME = "emit_graph_explanation"
_MAX_TOKENS = 2048
_BRIEF_MAX_TOKENS = 3072  # the brief schema (transmission path + exposures + observables) is larger
_COUNCIL_MAX_TOKENS = 768  # a verdict is small: stance + confidence + one short argument
_SANITY_MAX_TOKENS = 2048  # a batch of ~10 short verdicts, occasionally with a cleaned_text rewrite
_COMMUNITY_MAX_TOKENS = 2048  # a short verdict: sentiment + a handful of pros/cons/points
_EXPLAIN_MAX_TOKENS = 3072  # four markdown sections narrating a subgraph (people/orgs/signals)

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


def complete_sanity(
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    fallback: dict[str, Any],
    purpose: str = "live",
) -> LLMResult:
    """Produce a batch of content-sanity verdicts as structured JSON (``checkpoints/sanity.py``).
    Same forced-tool-call discipline as :func:`complete_card`; ``fallback`` is the deterministic
    all-``ok`` batch the ``mock`` provider returns verbatim — mock never rejects content it hasn't
    actually looked at."""
    return _complete(
        system,
        user,
        schema,
        fallback=fallback,
        purpose=purpose,
        tool_name=SANITY_TOOL_NAME,
        tool_description="Return one content-sanity verdict per raw_event_id given.",
        max_tokens=_SANITY_MAX_TOKENS,
    )


def complete_community(
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    fallback: dict[str, Any],
    purpose: str = "live",
) -> LLMResult:
    """Produce a cross-source community verdict as structured JSON — what the community thinks about
    an entity, distilled from its collected discussion comments. ``fallback`` is the deterministic
    verdict the ``mock`` provider returns verbatim (and the shape real providers must match).

    Runs on ``community_llm_provider``/``community_model`` when set, so the discussion summarizer
    can use a paid model while comprehension cards stay on the local one. Both fall back to the
    global provider/model when empty.

    ``strict_cli`` is the one behavioural difference from every other call site: this is a bulk
    backlog job, so a silently-substituted fallback would write hundreds of rows of placeholder
    prose that *read* like real verdicts. Failing loudly instead marks the row ``failed``, and the
    next run retries it."""
    return _complete(
        system,
        user,
        schema,
        fallback=fallback,
        purpose=purpose,
        tool_name=COMMUNITY_TOOL_NAME,
        tool_description="Return the community-opinion verdict for this entity.",
        max_tokens=_COMMUNITY_MAX_TOKENS,
        provider=settings.community_llm_provider or None,
        model=settings.community_model or None,
        strict_cli=True,
    )


def complete_graph_explanation(
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    fallback: dict[str, Any],
    purpose: str = "live",
) -> LLMResult:
    """Narrate one entity's relationship subgraph (who the people are, why each org appears,
    what the team pedigree signals) as structured markdown sections. Runs on
    ``graph_explain_provider``/``graph_explain_model`` when set — narrative synthesis wants a
    stronger model than the $0 card pipeline — falling back to the global provider when empty.

    ``strict_cli``: like the community backlog, this writes durable rows the dashboard serves —
    a silently-substituted fallback would read like a real explanation, so fail loudly instead."""
    return _complete(
        system,
        user,
        schema,
        fallback=fallback,
        purpose=purpose,
        tool_name=EXPLAIN_TOOL_NAME,
        tool_description="Return the narrated explanation of this relationship graph.",
        max_tokens=_EXPLAIN_MAX_TOKENS,
        provider=settings.graph_explain_provider or None,
        model=settings.graph_explain_model or None,
        strict_cli=True,
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
    provider: str | None = None,
    model: str | None = None,
    strict_cli: bool = False,
) -> LLMResult:
    """``provider``/``model`` override the global settings for one call site (see
    :func:`complete_community`); ``None`` keeps the global configuration.

    ``strict_cli`` flips the ``claude_cli`` failure policy from fail-closed (substitute the
    caller's deterministic ``fallback``) to fail-loud. Cards and briefs want the former — a
    degraded card beats a broken pipeline run. A bulk backlog wants the latter, because a
    substituted fallback is indistinguishable from a real generation once it is in the database."""
    provider = provider or settings.llm_provider
    if provider == "mock":
        return LLMResult(content=fallback, model="mock", cost_usd=Decimal(0))
    if provider == "ollama":
        return _ollama(system, user, schema, max_tokens, model=model)
    if provider == "anthropic":
        return _anthropic(
            system, user, schema, tool_name, tool_description, max_tokens, purpose, model=model
        )
    if provider == "claude_cli":
        # The card/brief `schema` is a plain JSON schema, so it maps 1:1 onto the CLI's
        # ``--json-schema`` structured-output flag (unlike Anthropic's forced-tool input_schema
        # wrapper).
        cli_model = model or settings.claude_cli_model
        usage = _claude_cli_metered(f"{system}\n\n{user}", schema, model=cli_model)
        if usage.parsed is None and strict_cli:
            raise RuntimeError(f"claude CLI returned no structured result ({usage.error})")
        return LLMResult(
            content=usage.parsed if usage.parsed is not None else fallback,
            # A failed CLI call must not carry the same model tag as a real generation (doc 13 —
            # this exact ambiguity produced a mislabeled comprehension-card version once already).
            model=(
                f"claude_cli:{cli_model}" if usage.parsed is not None else "claude_cli:fallback"
            ),
            # The CLI reports what the turn *would* have cost on the API. On a Claude Code
            # subscription nothing is billed, but it is still the only number available to meter
            # a long unattended run against ``llm_budget_usd``.
            cost_usd=usage.cost_usd,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
    raise ValueError(f"unknown LLM provider {provider!r}")


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    tier = next((k for k in _PRICE_PER_MTOK if k in model), "sonnet")
    price_in, price_out = _PRICE_PER_MTOK[tier]
    return (Decimal(input_tokens) * price_in + Decimal(output_tokens) * price_out) / Decimal(
        1_000_000
    )


def _ollama(
    system: str, user: str, schema: dict[str, Any], max_tokens: int, *, model: str | None = None
) -> LLMResult:
    import httpx

    model = model or settings.ollama_model
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


_CLAUDE_CLI_TIMEOUT_S = 300


def _first_json_object(reply: str) -> dict[str, Any] | None:
    """Extract the first complete JSON object from a free-text reply.

    Without a forced tool call the model's answer is prose-shaped: it may fence the JSON, precede
    it with "Here's the verdict:", or follow it with a note. Scanning for the first balanced
    ``{...}`` (string- and escape-aware, so braces inside quotes don't count) handles all three
    uniformly, where fence-stripping alone handled only one.
    """
    start = reply.find("{")
    if start < 0:
        return None
    depth, in_string, escaped = 0, False, False
    for i, ch in enumerate(reply[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(reply[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _anthropic(
    system: str,
    user: str,
    schema: dict[str, Any],
    tool_name: str,
    tool_description: str,
    max_tokens: int,
    purpose: str,
    *,
    model: str | None = None,
) -> LLMResult:
    import anthropic

    model = model or (settings.model_hindcast if purpose == "hindcast" else settings.model_live)
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


@dataclass
class CliOutcome:
    """What one ``claude -p`` invocation produced. ``parsed`` is ``None`` on any failure; the
    caller decides whether that means "use the fallback" or "raise" (see ``strict_cli``)."""

    parsed: dict[str, Any] | None
    cost_usd: Decimal = Decimal(0)
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""


_CLAUDE_CLI_RETRIES = 2  # replies are occasionally cut off mid-JSON on the largest prompts


def _claude_cli_metered(
    prompt: str,
    schema: dict[str, Any],
    *,
    timeout_s: int | None = None,
    model: str | None = None,
) -> CliOutcome:
    """Shell out to the installed ``claude`` CLI in non-interactive print mode with a JSON schema.

    Verified against the installed CLI: ``-p/--print`` (non-interactive), ``--model`` (alias or
    full snapshot id), ``--output-format json`` (wraps the reply in a single JSON result object)
    and ``--json-schema`` (constrain structured output) are all real flags. The wrapper carries the
    answer in ``result`` (and signals failures via ``is_error``); ``result`` may be a dict or a
    JSON-encoded string.

    **``--bare`` is deliberately not passed.** It suppresses keychain reads along with hooks and
    plugin sync, so the CLI cannot authenticate and every call comes back
    ``is_error: true, "Not logged in · Please run /login"``. Because this function fails closed,
    that failure is silent — callers just quietly get their deterministic fallback forever.
    Verified directly: identical invocation succeeds without the flag and fails with it.

    Fail-closed by contract: subprocess timeout, non-zero exit, unparseable JSON, an ``is_error``
    wrapper, or a missing/misshapen result all log a warning and return ``parsed=None`` — never
    raise. Retried once, because a truncated reply usually succeeds on a second attempt.
    """
    timeout = settings.claude_cli_timeout_s if timeout_s is None else timeout_s
    cmd = [
        settings.claude_cli_bin,
        "-p",
        "--model",
        model or settings.claude_cli_model,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
        prompt,
    ]
    outcome = CliOutcome(parsed=None)
    for attempt in range(1, _CLAUDE_CLI_RETRIES + 1):
        outcome = _claude_cli_once(cmd, timeout)
        if outcome.parsed is not None:
            return outcome
        logger.warning("claude_cli: attempt %d/%d failed — %s", attempt, _CLAUDE_CLI_RETRIES,
                       outcome.error)
    return outcome


def _claude_cli_once(cmd: list[str], timeout: int) -> CliOutcome:
    def fail(msg: str) -> CliOutcome:
        return CliOutcome(parsed=None, error=msg)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return fail(f"timed out after {timeout}s")
    except OSError as exc:  # binary missing / not executable
        return fail(f"could not launch {settings.claude_cli_bin!r} ({exc})")

    if proc.returncode != 0:
        return fail(f"exit {proc.returncode} — {(proc.stderr or '').strip()[:300]}")

    try:
        wrapper = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return fail(f"stdout was not JSON ({exc})")

    if wrapper.get("is_error"):
        return fail(f"CLI reported an error — {str(wrapper.get('result'))[:200]}")

    usage = wrapper.get("usage") or {}
    result = wrapper.get("result")
    if isinstance(result, str):
        # --json-schema normally yields clean JSON, but a model can still fence or preface it, so
        # fall back to scanning for the first balanced object rather than failing the whole call.
        result = _first_json_object(result)
    if not isinstance(result, dict):
        return fail(f"no structured result in reply: {str(wrapper.get('result'))[:200]!r}")

    return CliOutcome(
        parsed=result,
        cost_usd=Decimal(str(wrapper.get("total_cost_usd") or 0)),
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
    )


def _claude_cli(
    prompt: str, schema: dict[str, Any], *, timeout_s: int | None = None
) -> dict[str, Any] | None:
    """The parsed structured result, or ``None`` on any failure — the original fail-closed contract
    used by :func:`complete_triage`. Thin wrapper over :func:`_claude_cli_metered`, which is the
    single implementation; this exists so callers that have no use for token/cost accounting keep
    the simpler return type."""
    return _claude_cli_metered(prompt, schema, timeout_s=timeout_s).parsed


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
