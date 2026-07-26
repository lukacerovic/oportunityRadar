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
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from seismo.config import settings

CARD_TOOL_NAME = "emit_card"
BRIEF_TOOL_NAME = "emit_brief"
COMMUNITY_TOOL_NAME = "emit_community_verdict"
_MAX_TOKENS = 2048
_BRIEF_MAX_TOKENS = 3072  # the brief schema (transmission path + exposures + observables) is larger
_COMMUNITY_MAX_TOKENS = 2048  # a short verdict: sentiment + a handful of pros/cons/points

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


def complete_community(
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    fallback: dict[str, Any],
    purpose: str = "live",
) -> LLMResult:
    """Produce a cross-source community verdict as structured JSON — what the community thinks about
    an entity, distilled from its collected discussion comments. Same forced-tool-call discipline as
    :func:`complete_card`; ``fallback`` is the deterministic verdict the ``mock`` provider returns
    verbatim (and the shape real providers must match).

    Runs on ``community_llm_provider``/``community_model`` when set, so the discussion summarizer
    can use a paid model while comprehension cards stay on the local one. Both fall back to the
    global provider/model when empty."""
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
) -> LLMResult:
    """``provider``/``model`` override the global settings for one call site (see
    :func:`complete_community`); ``None`` keeps the global configuration."""
    provider = provider or settings.llm_provider
    if provider == "mock":
        return LLMResult(content=fallback, model="mock", cost_usd=Decimal(0))
    if provider == "ollama":
        return _ollama(system, user, schema, max_tokens, model=model)
    if provider == "claude_cli":
        return _claude_cli(system, user, schema, model=model)
    if provider == "anthropic":
        return _anthropic(
            system, user, schema, tool_name, tool_description, max_tokens, purpose, model=model
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


def _claude_cli(
    system: str, user: str, schema: dict[str, Any], *, model: str | None = None
) -> LLMResult:
    """Generate via the local ``claude`` CLI in headless mode, billed to the Claude Code
    subscription rather than to API credit.

    Chosen for the community summarizer when there is no API balance. Two things differ from
    :func:`_anthropic` and both matter:

    * **No forced tool call.** The CLI has no tool-schema parameter, so the schema is asked for in
      the prompt and the reply is parsed. Models often wrap JSON in a code fence, so the fence is
      stripped; ``_shape()`` in ``community.verdict`` is already defensive about missing keys.
    * **Roughly 24k tokens of Claude Code scaffolding ride along with every invocation** (its own
      system prompt and tool definitions, mostly cache-read). Measured at ~$0.016 on an empty
      prompt and $0.04–$0.05 on a real verdict, against ~$0.004 for the same work through the API.
      That overhead is the price of not needing credit — keep ``llm_budget_usd`` meaningful.

    The model is passed explicitly so the run is pinned to the configured model (Haiku) and does
    not inherit whatever model an interactive session happens to be using. The default system
    prompt is deliberately left in place: replacing it via ``--system-prompt`` busts the prompt
    cache and measured *more* expensive, not less.
    """
    model = model or settings.model_live or "haiku"
    prompt = (
        f"{system}\n\n"
        "Return ONLY a raw JSON object conforming to this schema. No prose, no code fences, no "
        "explanation before or after it.\n"
        f"{json.dumps(schema)}\n\n"
        # In a chat-shaped context the model treats thin input as a request it should clarify, and
        # replies asking for the comments — which is not an answer we can store. There is no user
        # to answer it: this is a batch job, and "not enough to say" is a legitimate verdict.
        "This is an automated batch call with no human to reply to. If the material below is "
        "missing, empty, truncated or too thin to judge, do NOT ask for more and do NOT explain "
        "yourself in prose — still return the JSON object, with overall_sentiment set to "
        "'insufficient_data' and the reason stated in the summary field.\n\n"
        f"{user}"
    )
    # One retry: replies occasionally come back cut off mid-JSON on the largest prompts, and the
    # same call succeeds immediately when repeated. Cheap insurance against re-running the whole
    # batch for a 0.5% intermittent failure. A reply that is genuinely prose fails twice and lands
    # a `failed` row, which the next run re-selects anyway.
    for attempt in (1, 2):
        try:
            return _claude_cli_once(prompt, model)
        except RuntimeError as exc:
            if attempt == 2 or "no JSON object" not in str(exc):
                raise
    raise AssertionError("unreachable")


def _claude_cli_once(prompt: str, model: str) -> LLMResult:
    import subprocess
    import tempfile

    try:
        proc = subprocess.run(
            [
                settings.claude_cli_bin,
                "-p",
                prompt,
                "--model",
                model,
                "--output-format",
                "json",
                "--allowed-tools",
                "",  # pure text generation — no file or shell access needed
                "--strict-mcp-config",  # don't load the user's MCP servers into every call
            ],
            capture_output=True,
            text=True,
            timeout=_CLAUDE_CLI_TIMEOUT_S,
            # Neutral cwd: run from the repo and every call would also carry its CLAUDE.md.
            cwd=tempfile.gettempdir(),
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"claude CLI not found at {settings.claude_cli_bin!r}; set SEISMO_CLAUDE_CLI_BIN to "
            "its absolute path (launchd and cron do not inherit an interactive PATH)"
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude CLI error: {str(envelope.get('result'))[:300]}")
    usage = envelope.get("usage") or {}
    raw = str(envelope.get("result") or "").strip()
    content = _first_json_object(raw)
    if content is None:
        # The model answered conversationally instead of emitting JSON. Surface what it actually
        # said; a bare "Expecting value: line 1 column 1" is undebuggable.
        raise RuntimeError(f"claude CLI returned no JSON object: {raw[:200]!r}")
    return LLMResult(
        content=content,
        model=f"claude_cli:{model}",
        # What the turn *would* have cost. On a subscription it draws against plan limits instead
        # of billing, but it is still the right number for llm_budget_usd to meter.
        cost_usd=Decimal(str(envelope.get("total_cost_usd") or 0)),
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
    )


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
