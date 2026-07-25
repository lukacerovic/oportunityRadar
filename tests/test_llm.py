"""LLM provider — the ``claude_cli`` backend and ``complete_triage`` (port Step 1).

All subprocess interaction is monkeypatched: CI stays $0 and hermetic, never touching the real
``claude`` binary or the network. Covers the fail-closed contract (timeout / non-zero exit /
malformed JSON all return ``None``, never raise) and the one happy path.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from seismo.checkpoints import llm

_SCHEMA = {
    "type": "object",
    "properties": {"decision": {"type": "string", "enum": ["track", "skip"]}},
    "required": ["decision"],
}


def _completed(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_triage_returns_none_for_mock_provider(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "llm_provider", "mock")
    assert llm.complete_triage({"name": "whatever"}) is None


def test_triage_returns_none_for_unimplemented_providers(monkeypatch) -> None:
    for provider in ("ollama", "anthropic"):
        monkeypatch.setattr(llm.settings, "llm_provider", provider)
        assert llm.complete_triage({"name": "x"}) is None


def test_claude_cli_returns_none_on_timeout(monkeypatch) -> None:
    def _raise(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=120)

    monkeypatch.setattr(subprocess, "run", _raise)
    assert llm._claude_cli("prompt", _SCHEMA) is None


def test_claude_cli_returns_none_on_nonzero_exit(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed("", returncode=1, stderr="boom")
    )
    assert llm._claude_cli("prompt", _SCHEMA) is None


def test_claude_cli_returns_none_on_malformed_json(monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed("not json at all"))
    assert llm._claude_cli("prompt", _SCHEMA) is None


def test_claude_cli_returns_none_when_cli_reports_error(monkeypatch) -> None:
    wrapper = json.dumps({"is_error": True, "result": "Not logged in"})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(wrapper))
    assert llm._claude_cli("prompt", _SCHEMA) is None


def test_claude_cli_parses_dict_result(monkeypatch) -> None:
    wrapper = json.dumps(
        {"type": "result", "is_error": False, "result": {"decision": "track", "sector": "ai"}}
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(wrapper))
    assert llm._claude_cli("prompt", _SCHEMA) == {"decision": "track", "sector": "ai"}


def test_claude_cli_parses_json_string_result(monkeypatch) -> None:
    # The wrapper's ``result`` may arrive as a JSON-encoded string rather than a nested object.
    wrapper = json.dumps(
        {"is_error": False, "result": json.dumps({"decision": "skip"})}
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(wrapper))
    assert llm._claude_cli("prompt", _SCHEMA) == {"decision": "skip"}


def test_triage_via_claude_cli_happy_path(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "llm_provider", "claude_cli")
    captured: dict = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        wrapper = json.dumps({"is_error": False, "result": {"decision": "track", "sector": "ml"}})
        return _completed(wrapper)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    result = llm.complete_triage({"name": "Acme", "funding_usd": 5_000_000})
    assert result == {"decision": "track", "sector": "ml"}
    # sanity-check the invocation actually used print mode + the schema flag
    assert "-p" in captured["cmd"]
    assert "--json-schema" in captured["cmd"]
    assert "--model" in captured["cmd"]


@pytest.mark.parametrize("bad_stdout", ['{"is_error": false}', '{"is_error": false, "result": 42}'])
def test_claude_cli_returns_none_on_missing_or_scalar_result(monkeypatch, bad_stdout) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(bad_stdout))
    assert llm._claude_cli("prompt", _SCHEMA) is None
