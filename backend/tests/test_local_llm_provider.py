"""Tests for the engine-neutral "local" LLM provider: provider resolution,
legacy "ollama_local" compatibility, saved capability tiers (survive a
restart, bad files can't break startup), and the settings API around them.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException

from backend import config, model_router
from backend.api import settings as settings_api
from backend.config import (
    DEFAULT_CAPABILITY_TIERS,
    load_saved_capability_tiers,
    normalize_capability_tiers,
    save_capability_tiers,
)
from backend.model_router import (
    AllProvidersFailedError,
    LocalLLMError,
    ModelRouter,
    resolve_provider,
)


@pytest.fixture
def tiers_path(tmp_path, monkeypatch):
    path = tmp_path / "capability_tiers.json"
    monkeypatch.setattr(config.settings, "CAPABILITY_TIERS_PATH", path)
    return path


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


def test_local_provider_prefers_new_base_url(monkeypatch):
    monkeypatch.setattr(config.settings, "LOCAL_LLM_BASE_URL", "http://localhost:8080")
    monkeypatch.setattr(config.settings, "OLLAMA_LOCAL_BASE_URL", "http://localhost:11434")
    assert resolve_provider("local") == ("http://localhost:8080", "")


def test_local_provider_defaults_to_llama_swap_not_ollama(monkeypatch):
    monkeypatch.setattr(config.settings, "LOCAL_LLM_BASE_URL", "")
    monkeypatch.setattr(config.settings, "LOCAL_LLM_ENGINE", "llama")
    monkeypatch.setattr(config.settings, "LLAMA_SWAP_BASE_URL", "http://localhost:8090")
    monkeypatch.setattr(config.settings, "OLLAMA_LOCAL_BASE_URL", "http://localhost:11434")
    assert resolve_provider("local") == ("http://localhost:8090", "")


def test_local_provider_uses_ollama_only_when_engine_says_so(monkeypatch):
    monkeypatch.setattr(config.settings, "LOCAL_LLM_BASE_URL", "")
    monkeypatch.setattr(config.settings, "LOCAL_LLM_ENGINE", "ollama")
    monkeypatch.setattr(config.settings, "OLLAMA_LOCAL_BASE_URL", "http://localhost:11434")
    assert resolve_provider("local") == ("http://localhost:11434", "")


def test_engine_rejects_unknown_value():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        config.Settings(LOCAL_LLM_ENGINE="lmstudio")


@pytest.mark.parametrize(
    "engine, path, reply",
    [
        ("llama", "/v1/chat/completions",
         {"choices": [{"message": {"role": "assistant", "content": "", "reasoning_content": "x",
                                   "tool_calls": [{"id": "c1", "function": {"name": "list_dir", "arguments": "{}"}}]}}]}),
        ("ollama", "/api/chat",
         {"message": {"role": "assistant", "content": "",
                      "tool_calls": [{"function": {"name": "list_dir", "arguments": {}}}]}}),
    ],
)
def test_dev_agent_uses_the_engines_wire_format(monkeypatch, engine, path, reply):
    from backend.tasks import dev_agent

    seen = {}

    class FakeResponse:
        def raise_for_status(self): ...
        def json(self): return reply

    class FakeClient:
        def __init__(self, **_): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *_): ...
        async def post(self, url, json):
            seen["url"], seen["json"] = url, json
            return FakeResponse()

    monkeypatch.setattr(dev_agent.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(config.settings, "LOCAL_LLM_BASE_URL", "")
    monkeypatch.setattr(config.settings, "LOCAL_LLM_ENGINE", engine)

    msg = asyncio.run(dev_agent._call_local_chat([{"role": "user", "content": "hi"}], "m"))

    assert seen["url"].endswith(path)
    assert ("options" in seen["json"]) == (engine == "ollama")
    assert msg["tool_calls"][0]["function"]["name"] == "list_dir"
    assert "reasoning_content" not in msg


def test_legacy_ollama_local_name_still_resolves(monkeypatch):
    monkeypatch.setattr(config.settings, "LOCAL_LLM_BASE_URL", "http://localhost:8080")
    assert resolve_provider("ollama_local") == resolve_provider("local")


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        resolve_provider("nope")


# ---------------------------------------------------------------------------
# Defaults and normalisation
# ---------------------------------------------------------------------------


def test_default_tiers_are_local_only():
    entries = [e for chain in DEFAULT_CAPABILITY_TIERS.values() for e in chain]
    assert {e["provider"] for e in entries} == {"local"}
    assert not [e for e in entries if e["model"].endswith("-cloud")]


def test_normalize_rewrites_legacy_provider_without_mutating_input():
    original = {"fast_text": [{"provider": "ollama_local", "model": "qwen3:8b"}]}
    result = normalize_capability_tiers(original)
    assert result == {"fast_text": [{"provider": "local", "model": "qwen3:8b"}]}
    assert original["fast_text"][0]["provider"] == "ollama_local"


def test_normalize_leaves_cloud_provider_alone():
    tiers = {"t": [{"provider": "ollama_cloud", "model": "m"}]}
    assert normalize_capability_tiers(tiers) == tiers


# ---------------------------------------------------------------------------
# Saved tiers
# ---------------------------------------------------------------------------


def test_save_then_load_roundtrip(tiers_path):
    tiers = {"fast_text": [{"provider": "local", "model": "qwen3:8b"}]}
    save_capability_tiers(tiers)
    assert load_saved_capability_tiers() == tiers


def test_load_returns_none_when_no_file(tiers_path):
    assert load_saved_capability_tiers() is None


def test_load_normalizes_legacy_provider(tiers_path):
    tiers_path.write_text(
        json.dumps({"fast_text": [{"provider": "ollama_local", "model": "qwen3:8b"}]}),
        encoding="utf-8",
    )
    assert load_saved_capability_tiers() == {
        "fast_text": [{"provider": "local", "model": "qwen3:8b"}]
    }


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        json.dumps(["a", "list"]),
        json.dumps({"fast_text": "not-a-list"}),
        json.dumps({"fast_text": [{"provider": "local"}]}),
    ],
)
def test_load_ignores_unusable_file(tiers_path, content):
    tiers_path.write_text(content, encoding="utf-8")
    assert load_saved_capability_tiers() is None


# ---------------------------------------------------------------------------
# Router fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_falls_through_failing_local_entry(monkeypatch):
    router = ModelRouter()
    router._tiers = {
        "t": [
            {"provider": "local", "model": "primary"},
            {"provider": "local", "model": "secondary"},
        ]
    }
    calls: list[str] = []

    async def fake_call(base_url, api_key, model, messages, image_base64, **kwargs):
        calls.append(model)
        if model == "primary":
            raise LocalLLMError("server down")
        return "ok"

    monkeypatch.setattr(router, "_make_chat_call", fake_call)
    content, used = await router.chat_with_meta("t", [{"role": "user", "content": "hi"}])
    assert (content, used) == ("ok", "secondary")
    assert calls == ["primary", "secondary"]


@pytest.mark.asyncio
async def test_router_raises_when_every_local_entry_fails(monkeypatch):
    router = ModelRouter()
    router._tiers = {"t": [{"provider": "local", "model": "only"}]}

    async def fake_call(*args, **kwargs):
        raise LocalLLMError("server down")

    monkeypatch.setattr(router, "_make_chat_call", fake_call)
    with pytest.raises(AllProvidersFailedError):
        await router.chat("t", [{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_router(monkeypatch):
    router = MagicMock()
    fake_main = types.SimpleNamespace(get_model_router=lambda: router)
    monkeypatch.setitem(sys.modules, "backend.main", fake_main)
    monkeypatch.setattr(config.settings, "CAPABILITY_TIERS", {})
    return router


@pytest.mark.asyncio
async def test_patch_saves_normalizes_and_applies(tiers_path, fake_router):
    body = settings_api.CapabilityTiersPatchRequest(
        tiers={"fast_text": [{"provider": "ollama_local", "model": "qwen3:8b"}]}
    )
    result = await settings_api.update_capability_tiers(body)

    expected = {"fast_text": [{"provider": "local", "model": "qwen3:8b"}]}
    assert result.tiers == expected
    assert fake_router._tiers == expected
    assert config.settings.CAPABILITY_TIERS == expected
    assert json.loads(tiers_path.read_text(encoding="utf-8")) == expected


@pytest.mark.asyncio
async def test_patch_leaves_state_unchanged_when_save_fails(tiers_path, fake_router, monkeypatch):
    def boom(_tiers):
        raise OSError("disk full")

    monkeypatch.setattr(settings_api, "save_capability_tiers", boom)
    body = settings_api.CapabilityTiersPatchRequest(
        tiers={"fast_text": [{"provider": "local", "model": "qwen3:8b"}]}
    )
    with pytest.raises(HTTPException) as exc_info:
        await settings_api.update_capability_tiers(body)
    assert exc_info.value.status_code == 500
    assert config.settings.CAPABILITY_TIERS == {}


@pytest.mark.asyncio
async def test_list_local_models_reads_v1_models(monkeypatch):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200, json={"data": [{"id": "qwen3:8b"}, {"id": "gemma4:26b"}, {"object": "no-id"}]}
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        settings_api.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(config.settings, "LOCAL_LLM_BASE_URL", "http://llm.test:8080/")

    result = await settings_api.list_local_models()
    assert [m.name for m in result.models] == ["qwen3:8b", "gemma4:26b"]
    assert seen == ["http://llm.test:8080/v1/models"]


@pytest.mark.asyncio
async def test_list_local_models_503_when_unreachable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        settings_api.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(HTTPException) as exc_info:
        await settings_api.list_local_models()
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_test_model_unknown_provider_is_not_reachable():
    result = await settings_api.test_model(
        settings_api.TestModelRequest(provider="nope", model="m")
    )
    assert result.reachable is False
    assert "Unknown provider" in result.detail


def test_module_exports_are_wired():
    # Guards the rename: nothing should still import the old exception name.
    assert not hasattr(model_router, "OllamaResourceError")
