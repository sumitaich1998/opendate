"""LLM provider-registry and router tests (offline; no real calls)."""

from __future__ import annotations

import pytest

from opendate.config import LLMConfig
from opendate.llm.providers import (
    PROVIDER_REGISTRY,
    list_providers,
    provider_ready,
    resolve_model,
)
from opendate.llm.router import EchoBackend, LLMResult, LLMRouter


def test_registry_has_western_and_chinese():
    western = list_providers(region="Western")
    chinese = list_providers(region="Chinese")
    assert len(western) >= 9
    assert len(chinese) >= 9
    assert "openai" in PROVIDER_REGISTRY
    assert "deepseek" in PROVIDER_REGISTRY
    assert "qwen" in PROVIDER_REGISTRY


def test_resolve_native_model():
    resolved = resolve_model("openai", "gpt-4o-mini", {"OPENAI_API_KEY": "k"})
    assert resolved.model == "openai/gpt-4o-mini"
    assert resolved.api_key == "k"


def test_resolve_openai_compatible_sets_base_url():
    resolved = resolve_model("zhipu", None, {"ZHIPUAI_API_KEY": "k"})
    assert resolved.model == "openai/glm-4-plus"  # routed through OpenAI handler
    assert resolved.api_base and "bigmodel.cn" in resolved.api_base
    assert resolved.api_key == "k"


def test_provider_ready():
    assert provider_ready("openai", {"OPENAI_API_KEY": "x"}) is True
    assert provider_ready("openai", {}) is False
    # Azure requires both a key and a base.
    assert provider_ready("azure", {"AZURE_API_KEY": "x"}) is False
    assert provider_ready("azure", {"AZURE_API_KEY": "x", "AZURE_API_BASE": "b"}) is True


def test_add_provider_is_one_entry():
    """The registry is a simple dict — adding one entry is all it takes."""
    from opendate.llm.providers import ProviderSpec

    before = len(PROVIDER_REGISTRY)
    spec = ProviderSpec(
        key="acme",
        label="Acme AI",
        region="Western",
        mode="openai_compatible",
        api_key_env="ACME_API_KEY",
        base_url="https://api.acme.test/v1",
        default_model="acme-1",
    )
    PROVIDER_REGISTRY[spec.key] = spec
    try:
        resolved = resolve_model("acme", None, {"ACME_API_KEY": "k"})
        assert resolved.model == "openai/acme-1"
        assert resolved.api_base == "https://api.acme.test/v1"
    finally:
        del PROVIDER_REGISTRY["acme"]
    assert len(PROVIDER_REGISTRY) == before


def test_echo_router_completes():
    router = LLMRouter.from_config(LLMConfig(provider="openai"), {}, stub=True)
    assert router.is_stub is True
    out = router.chat("system", "PRIMARY_SKILL: opener\nwrite an opener")
    assert isinstance(out, str) and out


@pytest.mark.asyncio
async def test_echo_router_acomplete():
    router = LLMRouter.from_config(LLMConfig(provider="openai"), {}, stub=True)
    result = await router.acomplete([{"role": "user", "content": "hi"}])
    assert isinstance(result, LLMResult)
    assert result.text


def test_router_fallback_on_failure():
    """First selection fails; router falls back to the second."""

    class FlakyBackend:
        def __init__(self):
            self.seen = []

        def complete(self, resolved, messages, **kwargs):
            self.seen.append(resolved.provider)
            if resolved.provider == "openai":
                raise RuntimeError("primary down")
            return LLMResult("ok", resolved.provider, resolved.model)

        def stream(self, *a, **k):  # pragma: no cover - not used here
            yield "ok"

    selections = [
        resolve_model("openai", "gpt-4o-mini", {}),
        resolve_model("deepseek", "deepseek-chat", {}),
    ]
    backend = FlakyBackend()
    router = LLMRouter(backend, selections, max_retries=1, retry_backoff=0)
    result = router.complete([{"role": "user", "content": "x"}])
    assert result.text == "ok"
    assert result.provider == "deepseek"
    assert backend.seen == ["openai", "deepseek"]


def test_router_raises_when_all_fail():
    class DeadBackend:
        def complete(self, resolved, messages, **kwargs):
            raise RuntimeError("nope")

        def stream(self, *a, **k):  # pragma: no cover
            raise RuntimeError("nope")

    router = LLMRouter(
        DeadBackend(),
        [resolve_model("openai", "gpt-4o-mini", {})],
        max_retries=1,
        retry_backoff=0,
    )
    with pytest.raises(RuntimeError):
        router.complete([{"role": "user", "content": "x"}])


def test_echo_backend_style_transfer_echo():
    """The stub echoes a delimited draft so style transfer stays coherent."""
    backend = EchoBackend()
    from opendate.llm.providers import resolve_model as rm

    result = backend.complete(
        rm("openai", "x", {}),
        [{"role": "user", "content": "rewrite this <<<DRAFT>>>hello you<<<END>>>"}],
    )
    assert result.text == "hello you"


# --- robustness: JSON helper, usage accounting, exponential backoff --------
def _responder_router(responder):
    backend = EchoBackend(responder=responder)
    return LLMRouter(
        backend, [resolve_model("openai", "gpt-4o-mini", {})], is_stub=True,
        retry_backoff=0,
    )


def test_extract_json_variants():
    from opendate.llm.router import extract_json

    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('noise before {"b": 2} and after') == {"b": 2}
    assert extract_json("definitely not json") is None


def test_chat_json_parses():
    router = _responder_router(lambda msgs: '{"score": 0.7, "ok": true}')
    assert router.chat_json("s", "u") == {"score": 0.7, "ok": True}


def test_chat_json_safe_fallback_on_garbage():
    router = _responder_router(lambda msgs: "totally not json at all")
    assert router.chat_json("s", "u", default={"score": 0.5}) == {"score": 0.5}


def test_router_tracks_usage_calls():
    router = _responder_router(lambda msgs: "hello")
    router.chat("s", "u")
    router.chat("s", "u")
    assert router.usage["calls"] == 2


def test_exponential_backoff_between_retries(monkeypatch):
    import opendate.llm.router as router_mod

    sleeps: list[float] = []
    monkeypatch.setattr(router_mod.time, "sleep", lambda s: sleeps.append(s))

    class Flaky:
        def __init__(self):
            self.n = 0

        def complete(self, resolved, messages, **kwargs):
            self.n += 1
            if self.n < 3:
                raise RuntimeError("boom")
            return LLMResult("ok", resolved.provider, resolved.model)

        def stream(self, *a, **k):  # pragma: no cover - unused
            yield "ok"

    router = LLMRouter(
        Flaky(), [resolve_model("openai", "m", {})], max_retries=3, retry_backoff=0.5
    )
    result = router.complete([{"role": "user", "content": "x"}])
    assert result.text == "ok"
    # Backoff doubles: 0.5 * 2^0, then 0.5 * 2^1.
    assert sleeps == [0.5, 1.0]
