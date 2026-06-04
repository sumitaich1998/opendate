"""Provider registry: friendly key -> how to call it through ``litellm``.

OpenDate supports a broad set of LLM providers, both American/Western and
Chinese. Two integration modes are used:

* ``native`` — the provider has first-class support in ``litellm``. We build the
  model string as ``"{litellm_prefix}/{model}"`` (e.g. ``"anthropic/claude-..."``)
  and pass the API key explicitly.
* ``openai_compatible`` — the provider exposes an OpenAI-compatible endpoint.
  We route through litellm's OpenAI handler with a custom ``api_base`` (a
  ``base_url``) and the provider's API key. This is how most Chinese providers
  are reached.

**Adding a new provider is intentionally trivial:** append one
:class:`ProviderSpec` to :data:`PROVIDER_REGISTRY`. Nothing else needs to change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping

__all__ = [
    "ProviderSpec",
    "ResolvedModel",
    "PROVIDER_REGISTRY",
    "list_providers",
    "get_provider",
    "resolve_model",
    "provider_ready",
]

Region = Literal["Western", "Chinese"]
Mode = Literal["native", "openai_compatible"]


@dataclass(frozen=True)
class ProviderSpec:
    """Everything OpenDate needs to know to call a provider via litellm."""

    key: str
    """Friendly key used in config, e.g. ``"openai"`` or ``"deepseek"``."""

    label: str
    """Human-readable vendor name, e.g. ``"OpenAI"``."""

    region: Region
    mode: Mode

    api_key_env: str
    """Environment variable that holds the provider's API key."""

    default_model: str
    """Sane default model name (without the provider prefix)."""

    example_models: tuple[str, ...] = ()
    """Illustrative model names shown by ``opendate providers``."""

    litellm_prefix: str | None = None
    """For ``native`` mode: the litellm provider prefix (e.g. ``"gemini"``)."""

    base_url: str | None = None
    """Default OpenAI-compatible endpoint for ``openai_compatible`` providers."""

    base_url_env: str | None = None
    """Optional env var that overrides :attr:`base_url` (or sets Azure base)."""

    requires_api_base: bool = False
    """True when an api_base is mandatory (e.g. Azure OpenAI)."""

    notes: str = ""

    def env_keys(self) -> list[str]:
        """All env vars relevant to this provider (key + optional base url)."""
        keys = [self.api_key_env]
        if self.base_url_env:
            keys.append(self.base_url_env)
        return keys


@dataclass(frozen=True)
class ResolvedModel:
    """Concrete kwargs ready to hand to ``litellm.completion``."""

    provider: str
    model: str
    api_key: str | None = None
    api_base: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def to_litellm_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {"model": self.model}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        kwargs.update(self.extra)
        return kwargs


# ---------------------------------------------------------------------------
# The registry. One entry per provider route. Add a line to add a provider.
# ---------------------------------------------------------------------------

_PROVIDERS: tuple[ProviderSpec, ...] = (
    # ---------------------------- Western ---------------------------------
    ProviderSpec(
        key="openai",
        label="OpenAI",
        region="Western",
        mode="native",
        litellm_prefix="openai",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
        example_models=("gpt-4o", "gpt-4.1", "o3-mini"),
    ),
    ProviderSpec(
        key="anthropic",
        label="Anthropic",
        region="Western",
        mode="native",
        litellm_prefix="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-3-5-sonnet-latest",
        example_models=("claude-3-5-sonnet-latest", "claude-3-opus-latest"),
    ),
    ProviderSpec(
        key="gemini",
        label="Google (Gemini)",
        region="Western",
        mode="native",
        litellm_prefix="gemini",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-1.5-flash",
        example_models=("gemini-2.0-flash", "gemini-1.5-pro"),
    ),
    ProviderSpec(
        key="xai",
        label="xAI (Grok)",
        region="Western",
        mode="native",
        litellm_prefix="xai",
        api_key_env="XAI_API_KEY",
        default_model="grok-2-latest",
        example_models=("grok-2-latest", "grok-beta"),
    ),
    ProviderSpec(
        key="groq",
        label="Groq (Meta Llama)",
        region="Western",
        mode="native",
        litellm_prefix="groq",
        api_key_env="GROQ_API_KEY",
        default_model="llama-3.3-70b-versatile",
        example_models=("llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
        notes="Fast hosting for Meta Llama models.",
    ),
    ProviderSpec(
        key="together",
        label="Together (Meta Llama)",
        region="Western",
        mode="native",
        litellm_prefix="together_ai",
        api_key_env="TOGETHER_API_KEY",
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        example_models=("meta-llama/Llama-3.3-70B-Instruct-Turbo",),
        notes="Open models incl. Meta Llama, hosted by Together AI.",
    ),
    ProviderSpec(
        key="mistral",
        label="Mistral",
        region="Western",
        mode="native",
        litellm_prefix="mistral",
        api_key_env="MISTRAL_API_KEY",
        default_model="mistral-large-latest",
        example_models=("mistral-large-latest", "mistral-small-latest"),
    ),
    ProviderSpec(
        key="cohere",
        label="Cohere",
        region="Western",
        mode="native",
        litellm_prefix="cohere",
        api_key_env="COHERE_API_KEY",
        default_model="command-r-plus",
        example_models=("command-r-plus", "command-r"),
    ),
    ProviderSpec(
        key="bedrock",
        label="AWS Bedrock",
        region="Western",
        mode="native",
        litellm_prefix="bedrock",
        api_key_env="AWS_ACCESS_KEY_ID",
        default_model="anthropic.claude-3-5-sonnet-20240620-v1:0",
        example_models=(
            "anthropic.claude-3-5-sonnet-20240620-v1:0",
            "meta.llama3-1-70b-instruct-v1:0",
        ),
        notes=(
            "Uses standard AWS credentials (AWS_ACCESS_KEY_ID / "
            "AWS_SECRET_ACCESS_KEY / AWS_REGION_NAME) rather than a single key."
        ),
    ),
    ProviderSpec(
        key="azure",
        label="Azure OpenAI",
        region="Western",
        mode="native",
        litellm_prefix="azure",
        api_key_env="AZURE_API_KEY",
        base_url_env="AZURE_API_BASE",
        requires_api_base=True,
        default_model="gpt-4o",
        example_models=("gpt-4o", "gpt-4o-mini"),
        notes="`model` is your Azure *deployment* name. Set AZURE_API_BASE.",
    ),
    # ---------------------------- Chinese ---------------------------------
    ProviderSpec(
        key="deepseek",
        label="DeepSeek",
        region="Chinese",
        mode="native",
        litellm_prefix="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-chat",
        example_models=("deepseek-chat", "deepseek-reasoner"),
    ),
    ProviderSpec(
        key="qwen",
        label="Alibaba Qwen (DashScope)",
        region="Chinese",
        mode="openai_compatible",
        api_key_env="DASHSCOPE_API_KEY",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        base_url_env="DASHSCOPE_API_BASE",
        default_model="qwen-plus",
        example_models=("qwen-max", "qwen-plus", "qwen2.5-72b-instruct"),
    ),
    ProviderSpec(
        key="zhipu",
        label="Zhipu AI (GLM)",
        region="Chinese",
        mode="openai_compatible",
        api_key_env="ZHIPUAI_API_KEY",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        base_url_env="ZHIPUAI_API_BASE",
        default_model="glm-4-plus",
        example_models=("glm-4-plus", "glm-4-air"),
    ),
    ProviderSpec(
        key="moonshot",
        label="Moonshot (Kimi)",
        region="Chinese",
        mode="openai_compatible",
        api_key_env="MOONSHOT_API_KEY",
        base_url="https://api.moonshot.cn/v1",
        base_url_env="MOONSHOT_API_BASE",
        default_model="moonshot-v1-8k",
        example_models=("moonshot-v1-8k", "moonshot-v1-32k", "kimi-latest"),
    ),
    ProviderSpec(
        key="baidu",
        label="Baidu (ERNIE)",
        region="Chinese",
        mode="openai_compatible",
        api_key_env="QIANFAN_API_KEY",
        base_url="https://qianfan.baidubce.com/v2",
        base_url_env="QIANFAN_API_BASE",
        default_model="ernie-4.0-8k",
        example_models=("ernie-4.0-8k", "ernie-3.5-8k"),
    ),
    ProviderSpec(
        key="yi",
        label="01.AI (Yi)",
        region="Chinese",
        mode="openai_compatible",
        api_key_env="YI_API_KEY",
        base_url="https://api.lingyiwanwu.com/v1",
        base_url_env="YI_API_BASE",
        default_model="yi-large",
        example_models=("yi-large", "yi-medium"),
    ),
    ProviderSpec(
        key="minimax",
        label="MiniMax",
        region="Chinese",
        mode="openai_compatible",
        api_key_env="MINIMAX_API_KEY",
        base_url="https://api.minimax.chat/v1",
        base_url_env="MINIMAX_API_BASE",
        default_model="abab6.5s-chat",
        example_models=("abab6.5s-chat", "abab6.5-chat"),
    ),
    ProviderSpec(
        key="hunyuan",
        label="Tencent (Hunyuan)",
        region="Chinese",
        mode="openai_compatible",
        api_key_env="HUNYUAN_API_KEY",
        base_url="https://api.hunyuan.cloud.tencent.com/v1",
        base_url_env="HUNYUAN_API_BASE",
        default_model="hunyuan-standard",
        example_models=("hunyuan-standard", "hunyuan-pro"),
    ),
    ProviderSpec(
        key="doubao",
        label="ByteDance (Doubao)",
        region="Chinese",
        mode="openai_compatible",
        api_key_env="ARK_API_KEY",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        base_url_env="ARK_API_BASE",
        default_model="doubao-pro-32k",
        example_models=("doubao-pro-32k", "doubao-lite-32k"),
        notes="Doubao is served through Volcengine Ark; `model` is your endpoint id.",
    ),
)

PROVIDER_REGISTRY: dict[str, ProviderSpec] = {p.key: p for p in _PROVIDERS}


def list_providers(region: Region | None = None) -> list[ProviderSpec]:
    """Return all provider specs, optionally filtered by region."""
    specs = list(PROVIDER_REGISTRY.values())
    if region is not None:
        specs = [s for s in specs if s.region == region]
    return specs


def get_provider(key: str) -> ProviderSpec:
    """Look up a provider spec by friendly key (raises ``KeyError``)."""
    try:
        return PROVIDER_REGISTRY[key]
    except KeyError as exc:  # pragma: no cover - trivial
        known = ", ".join(sorted(PROVIDER_REGISTRY))
        raise KeyError(
            f"Unknown LLM provider {key!r}. Known providers: {known}"
        ) from exc


def _lookup(secrets: Mapping[str, str | None] | None, name: str) -> str | None:
    """Resolve an env var from an explicit mapping, falling back to os.environ."""
    if secrets is not None and name in secrets and secrets[name]:
        return secrets[name]
    return os.environ.get(name)


def resolve_model(
    provider: str,
    model: str | None = None,
    secrets: Mapping[str, str | None] | None = None,
) -> ResolvedModel:
    """Resolve ``(provider, model)`` into concrete litellm call parameters.

    ``secrets`` maps environment-variable names to values (as loaded by the
    config layer). When omitted or missing a value, ``os.environ`` is used.
    """
    spec = get_provider(provider)
    model_name = model or spec.default_model
    api_key = _lookup(secrets, spec.api_key_env)

    api_base: str | None = None
    if spec.base_url_env:
        api_base = _lookup(secrets, spec.base_url_env) or spec.base_url
    else:
        api_base = spec.base_url

    if spec.mode == "native":
        full_model = (
            f"{spec.litellm_prefix}/{model_name}"
            if spec.litellm_prefix
            else model_name
        )
        return ResolvedModel(
            provider=provider,
            model=full_model,
            api_key=api_key,
            api_base=api_base,
        )

    # openai_compatible: route through litellm's OpenAI handler with a base_url.
    return ResolvedModel(
        provider=provider,
        model=f"openai/{model_name}",
        api_key=api_key,
        api_base=api_base,
    )


def provider_ready(
    provider: str,
    secrets: Mapping[str, str | None] | None = None,
) -> bool:
    """Return True if the credentials needed to call ``provider`` are present."""
    spec = get_provider(provider)
    if _lookup(secrets, spec.api_key_env) is None:
        return False
    if spec.requires_api_base:
        if spec.base_url_env and _lookup(secrets, spec.base_url_env) is None:
            return False
    return True
