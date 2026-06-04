"""LLM access layer for OpenDate.

A single :class:`~opendate.llm.router.LLMRouter` (built on ``litellm``) speaks to
every supported provider — American/Western and Chinese alike — selected by a
friendly key + model name from config. See :mod:`opendate.llm.providers` for the
provider registry and :mod:`opendate.llm.router` for the router itself.
"""

from __future__ import annotations

from .providers import (
    PROVIDER_REGISTRY,
    ProviderSpec,
    ResolvedModel,
    list_providers,
    resolve_model,
)
from .router import EchoBackend, LiteLLMBackend, LLMRouter, LLMResult

__all__ = [
    "PROVIDER_REGISTRY",
    "ProviderSpec",
    "ResolvedModel",
    "list_providers",
    "resolve_model",
    "LLMRouter",
    "LLMResult",
    "LiteLLMBackend",
    "EchoBackend",
]
