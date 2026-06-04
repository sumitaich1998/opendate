"""LLM provider-registry and router tests (offline; no real calls)."""

from __future__ import annotations

import pytest

from opendate.config import LLMConfig, LLMFallback
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

    cfg = LLMConfig(
        provider="openai",
        model="gpt-4o-mini",
        max_retries=1,
        fallbacks=[LLMFallback(provider="deepseek", model="deepseek-chat")],
    )
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
