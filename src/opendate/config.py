"""Configuration & secrets for OpenDate.

* **Non-secret config** (preferences, relationship intent, provider/model
  selection, persona sources, ``auto_send`` …) lives in a YAML file and is
  validated by pydantic models.
* **Secrets** (the Tinder token and every LLM provider key) are loaded by
  :class:`Secrets`, a ``pydantic-settings`` model that reads from the
  environment and an optional ``.env`` file. Secrets are *registered for
  redaction* the moment they are loaded so they can never leak into logs.

Nothing in this module ever prints or logs a secret value.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .llm.providers import PROVIDER_REGISTRY
from .utils.logging import register_secret

__all__ = [
    "RelationshipIntent",
    "AgeRange",
    "Preferences",
    "LLMFallback",
    "LLMConfig",
    "PersonaBlend",
    "PersonaSources",
    "SafetyConfig",
    "AppConfig",
    "Secrets",
    "load_config",
    "load_secrets",
    "EXAMPLE_CONFIG_YAML",
    "EXAMPLE_ENV",
]


# ---------------------------------------------------------------------------
# Preferences / intent
# ---------------------------------------------------------------------------
class RelationshipIntent(str, Enum):
    """What the user is looking for. Drives tone, pacing, and skill choice."""

    CASUAL = "casual"
    DATING = "dating"
    LONG_TERM = "long-term"


class AgeRange(BaseModel):
    min: int = Field(ge=18, le=120, description="Minimum acceptable age (>=18).")
    max: int = Field(ge=18, le=120, description="Maximum acceptable age.")

    @model_validator(mode="after")
    def _check_order(self) -> "AgeRange":
        if self.min > self.max:
            raise ValueError("age_range.min must be <= age_range.max")
        return self

    def contains(self, age: int | None) -> bool:
        if age is None:
            return True  # unknown age is not a hard fail; screening can weigh it
        return self.min <= age <= self.max


class Preferences(BaseModel):
    """Who you want to meet and what you're looking for."""

    looking_for: RelationshipIntent = RelationshipIntent.DATING
    also_open_to: list[RelationshipIntent] = Field(default_factory=list)
    partner_traits: list[str] = Field(default_factory=list)
    dealbreakers: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    age_range: AgeRange = Field(default_factory=lambda: AgeRange(min=25, max=40))
    distance_km: int = Field(default=40, ge=1, le=500)
    voice: str = Field(
        default="warm, curious, a little playful",
        description="Stated tone for your messages (a persona signal).",
    )

    @field_validator("partner_traits", "dealbreakers", "interests", mode="before")
    @classmethod
    def _coerce_csv(cls, value: Any) -> Any:
        # Allow a comma-separated string in YAML as a convenience.
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


# ---------------------------------------------------------------------------
# LLM selection
# ---------------------------------------------------------------------------
class LLMFallback(BaseModel):
    provider: str
    model: str | None = None

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        if value not in PROVIDER_REGISTRY:
            known = ", ".join(sorted(PROVIDER_REGISTRY))
            raise ValueError(f"Unknown provider {value!r}. Known: {known}")
        return value


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str | None = None
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    max_tokens: int = Field(default=600, ge=1, le=8192)
    max_retries: int = Field(default=2, ge=1, le=10)
    timeout: float = Field(default=60.0, ge=1.0)
    streaming: bool = False
    fallbacks: list[LLMFallback] = Field(default_factory=list)

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        if value not in PROVIDER_REGISTRY:
            known = ", ".join(sorted(PROVIDER_REGISTRY))
            raise ValueError(f"Unknown provider {value!r}. Known: {known}")
        return value


# ---------------------------------------------------------------------------
# Persona sources / blend
# ---------------------------------------------------------------------------
class PersonaBlend(BaseModel):
    """Weighting of persona signals. Defaults match the OpenDate blueprint."""

    social_posts: float = 0.40
    past_chats: float = 0.35
    stated_preferences: float = 0.25

    @model_validator(mode="after")
    def _normalize(self) -> "PersonaBlend":
        total = self.social_posts + self.past_chats + self.stated_preferences
        if total <= 0:
            raise ValueError("persona blend weights must sum to > 0")
        # Normalize so the three weights always sum to 1.0.
        self.social_posts /= total
        self.past_chats /= total
        self.stated_preferences /= total
        return self

    def as_dict(self) -> dict[str, float]:
        return {
            "social_posts": self.social_posts,
            "past_chats": self.past_chats,
            "stated_preferences": self.stated_preferences,
        }


class PersonaSources(BaseModel):
    """Where the persona signal comes from, and where the profile is cached."""

    social_posts: list[str] = Field(default_factory=list)
    chat_history: list[str] = Field(default_factory=list)
    my_names: list[str] = Field(
        default_factory=list,
        description="Your name/handles, used to pick out *your* lines in chat exports.",
    )
    profile_path: str = "persona.json"
    blend: PersonaBlend = Field(default_factory=PersonaBlend)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------
class SafetyConfig(BaseModel):
    require_consent_checks: bool = True
    allow_explicit: bool = False
    backoff_on_disinterest: bool = True
    max_followups_without_reply: int = Field(default=2, ge=0, le=10)


# ---------------------------------------------------------------------------
# Top-level app config
# ---------------------------------------------------------------------------
class AppConfig(BaseModel):
    source: str = Field(default="tinder", description="'tinder' or 'mock'.")
    auto_send: bool = Field(
        default=False,
        description="When false, OpenDate proposes actions and asks before sending.",
    )
    poll_interval: int = Field(default=120, ge=5, description="Seconds between cycles.")
    max_actions_per_cycle: int = Field(default=5, ge=1, le=100)
    max_screen_per_cycle: int = Field(default=10, ge=0, le=100)
    log_level: str = "INFO"

    preferences: Preferences = Field(default_factory=Preferences)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    persona: PersonaSources = Field(default_factory=PersonaSources)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in {"tinder", "mock"}:
            raise ValueError("source must be 'tinder' or 'mock'")
        return value


# ---------------------------------------------------------------------------
# Secrets (pydantic-settings)
# ---------------------------------------------------------------------------
class Secrets(BaseSettings):
    """Secret values from the environment / ``.env``. Never logged."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Match source
    tinder_auth_token: str | None = None

    # Western providers
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    xai_api_key: str | None = None
    groq_api_key: str | None = None
    together_api_key: str | None = None
    mistral_api_key: str | None = None
    cohere_api_key: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region_name: str | None = None
    azure_api_key: str | None = None
    azure_api_base: str | None = None

    # Chinese providers
    deepseek_api_key: str | None = None
    dashscope_api_key: str | None = None
    dashscope_api_base: str | None = None
    zhipuai_api_key: str | None = None
    zhipuai_api_base: str | None = None
    moonshot_api_key: str | None = None
    moonshot_api_base: str | None = None
    qianfan_api_key: str | None = None
    qianfan_api_base: str | None = None
    yi_api_key: str | None = None
    yi_api_base: str | None = None
    minimax_api_key: str | None = None
    minimax_api_base: str | None = None
    hunyuan_api_key: str | None = None
    hunyuan_api_base: str | None = None
    ark_api_key: str | None = None
    ark_api_base: str | None = None

    def register_for_redaction(self) -> None:
        """Register every loaded secret value so logs can mask them."""
        for name, value in self.model_dump().items():
            if value and name.endswith(("_key", "_token", "_id")) or (
                value and name == "tinder_auth_token"
            ):
                register_secret(value)
        register_secret(self.tinder_auth_token)

    def env_map(self) -> dict[str, str | None]:
        """Build the {ENV_VAR: value} mapping used by the provider resolver.

        Values declared here take precedence; anything not declared falls back
        to the live process environment so new providers work automatically.
        """
        data: dict[str, str | None] = {}
        wanted: set[str] = {"AWS_SECRET_ACCESS_KEY", "AWS_REGION_NAME"}
        for spec in PROVIDER_REGISTRY.values():
            wanted.update(spec.env_keys())
        for env in wanted:
            value = getattr(self, env.lower(), None)
            data[env] = value if value is not None else os.environ.get(env)
        return data


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
_DEFAULT_CONFIG_NAMES = ("opendate.config.yaml", "opendate.yaml", "config.yaml")


def _find_default_config() -> Path | None:
    for name in _DEFAULT_CONFIG_NAMES:
        candidate = Path(name)
        if candidate.exists():
            return candidate
    return None


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    """Load and validate an :class:`AppConfig` from a YAML file.

    If ``path`` is ``None`` we look for common default filenames; if none are
    found we return defaults (handy for ``--mock`` demos with no config file).
    """
    resolved = Path(path) if path else _find_default_config()
    if resolved is None:
        return AppConfig()
    if not resolved.exists():
        raise FileNotFoundError(f"Config file not found: {resolved}")
    with resolved.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config file {resolved} must contain a YAML mapping")
    return AppConfig.model_validate(raw)


def load_secrets(env_file: str | os.PathLike[str] | None = ".env") -> Secrets:
    """Load secrets from the environment + an optional ``.env`` file."""
    if env_file and Path(env_file).exists():
        secrets = Secrets(_env_file=str(env_file))  # type: ignore[call-arg]
    else:
        secrets = Secrets()
    secrets.register_for_redaction()
    return secrets


# ---------------------------------------------------------------------------
# Example templates (single source of truth for `opendate init` + repo files)
# ---------------------------------------------------------------------------
EXAMPLE_CONFIG_YAML = """\
# OpenDate configuration (non-secret). Secrets live in .env — never here.
# Run `opendate providers` to see all provider keys and example models.

# Where to pull dates/matches from: "tinder" (real) or "mock" (offline demo).
source: tinder

# Human-in-the-loop. When false, OpenDate shows each proposed action/message
# and asks for confirmation before anything is sent. Set true to let it act.
auto_send: false

poll_interval: 120          # seconds between runtime-loop cycles
max_actions_per_cycle: 5    # cap on messages/proposals per cycle
max_screen_per_cycle: 10    # cap on candidates screened per cycle
log_level: INFO

# --- Who you want to meet -------------------------------------------------
preferences:
  looking_for: long-term            # casual | dating | long-term
  also_open_to: [dating]
  partner_traits: [witty, outdoorsy, ambitious, kind]
  dealbreakers: [smoking]
  interests: [climbing, live music, cooking, travel]
  age_range:
    min: 26
    max: 34
  distance_km: 25
  voice: warm, curious, a little sarcastic

# --- Which model to use ---------------------------------------------------
llm:
  provider: openai                  # any key from `opendate providers`
  model: gpt-4o-mini                # omit to use the provider's default
  temperature: 0.8
  max_tokens: 600
  streaming: false
  # Try these in order if the primary provider fails:
  fallbacks:
    - provider: anthropic
      model: claude-3-5-sonnet-latest
    - provider: deepseek
      model: deepseek-chat

# --- Learning your voice --------------------------------------------------
persona:
  social_posts:
    - data/my_posts.txt             # plain text (one post per line) or .json
  chat_history:
    - data/my_chats.json            # list of {"sender": "...", "text": "..."}
  my_names: [me, "Your Name"]       # used to pick out YOUR lines in exports
  profile_path: persona.json        # where the learned profile is cached
  blend:
    social_posts: 0.40
    past_chats: 0.35
    stated_preferences: 0.25

# --- Safety guardrails (on by default) ------------------------------------
safety:
  require_consent_checks: true
  allow_explicit: false
  backoff_on_disinterest: true
  max_followups_without_reply: 2
"""

EXAMPLE_ENV = """\
# OpenDate secrets. Copy to .env and fill in only what you use. NEVER commit .env.

# --- Match source ---------------------------------------------------------
# Your Tinder auth token (sent as the X-Auth-Token header). Unofficial API.
TINDER_AUTH_TOKEN=

# --- Pick ONE LLM provider key (or several for fallbacks) -----------------
# Western / American providers
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
XAI_API_KEY=
GROQ_API_KEY=
TOGETHER_API_KEY=
MISTRAL_API_KEY=
COHERE_API_KEY=
# AWS Bedrock uses standard AWS credentials:
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION_NAME=us-east-1
# Azure OpenAI:
AZURE_API_KEY=
AZURE_API_BASE=

# Chinese providers (most are OpenAI-compatible; base URLs have sane defaults)
DEEPSEEK_API_KEY=
DASHSCOPE_API_KEY=            # Alibaba Qwen
ZHIPUAI_API_KEY=             # Zhipu GLM
MOONSHOT_API_KEY=            # Moonshot Kimi
QIANFAN_API_KEY=            # Baidu ERNIE
YI_API_KEY=                 # 01.AI Yi
MINIMAX_API_KEY=
HUNYUAN_API_KEY=            # Tencent Hunyuan
ARK_API_KEY=                # ByteDance Doubao (Volcengine Ark)
"""
