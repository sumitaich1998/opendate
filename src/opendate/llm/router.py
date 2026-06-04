"""LLMRouter — one interface over every provider, with retries + fallback.

The router is deliberately backend-agnostic:

* :class:`LiteLLMBackend` performs real calls through ``litellm`` (imported
  lazily so the rest of OpenDate — and the whole test suite — works offline).
* :class:`EchoBackend` is a deterministic, network-free stub used by ``--mock``
  and the tests. A router built on it reports ``is_stub == True`` so persona /
  style code can fall back to heuristics instead of round-tripping a fake LLM.

A router holds an ordered list of model *selections* (primary + fallbacks). On a
failure it retries the current selection a few times, then falls back to the
next one. Selections are resolved through :mod:`opendate.llm.providers`.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol, Sequence

from ..utils.logging import get_logger, register_secret
from .providers import ResolvedModel, provider_ready, resolve_model

__all__ = [
    "Message",
    "LLMResult",
    "LLMBackend",
    "LiteLLMBackend",
    "EchoBackend",
    "LLMRouter",
    "extract_json",
]

log = get_logger("llm.router")

# A chat message is the standard ``{"role": ..., "content": ...}`` dict.
Message = dict[str, str]


@dataclass
class LLMResult:
    """The result of a completion call."""

    text: str
    provider: str
    model: str
    raw: object | None = None
    usage: dict[str, int] | None = None


def extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort: pull the first JSON object out of ``text`` (or return None).

    Tolerates code fences and chatty preambles around the JSON, which real
    models love to add despite instructions.
    """
    if not text:
        return None
    # Strip ```json fences if present.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    blob = fenced.group(1) if fenced else None
    if blob is None:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        blob = match.group(0) if match else None
    if blob is None:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class LLMBackend(Protocol):
    """Strategy interface for performing completions."""

    def complete(
        self,
        resolved: ResolvedModel,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> LLMResult: ...

    def stream(
        self,
        resolved: ResolvedModel,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> Iterator[str]: ...


def _usage_from_response(response: object) -> dict[str, int] | None:
    """Defensively pull token counts out of a provider response object."""
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return None
    out: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(key)
        if isinstance(value, (int, float)):
            out[key] = int(value)
    return out or None


class LiteLLMBackend:
    """Real backend backed by ``litellm`` (imported lazily)."""

    def __init__(self) -> None:
        self._litellm = None

    def _lib(self):
        if self._litellm is None:
            import litellm  # noqa: PLC0415 - lazy import keeps tests offline

            litellm.drop_params = True
            litellm.suppress_debug_info = True
            self._litellm = litellm
        return self._litellm

    def complete(
        self,
        resolved: ResolvedModel,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> LLMResult:
        litellm = self._lib()
        kwargs = resolved.to_litellm_kwargs()
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = litellm.completion(messages=list(messages), **kwargs)
        text = ""
        try:
            text = response.choices[0].message.content or ""
        except (AttributeError, IndexError, KeyError):  # pragma: no cover
            text = str(response)
        return LLMResult(
            text=text,
            provider=resolved.provider,
            model=resolved.model,
            raw=response,
            usage=_usage_from_response(response),
        )

    def stream(
        self,
        resolved: ResolvedModel,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> Iterator[str]:
        litellm = self._lib()
        kwargs = resolved.to_litellm_kwargs()
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if timeout is not None:
            kwargs["timeout"] = timeout
        for chunk in litellm.completion(
            messages=list(messages), stream=True, **kwargs
        ):
            try:
                delta = chunk.choices[0].delta.content
            except (AttributeError, IndexError, KeyError):  # pragma: no cover
                delta = None
            if delta:
                yield delta


# Deterministic, skill-aware canned drafts for the offline stub so the --mock
# demo produces sensible, varied messages without any network/LLM.
_STUB_DRAFTS: dict[str, str] = {
    "opener": (
        "Okay, your profile genuinely made me smile — I have to ask about it. "
        "What's been the highlight of your week so far?"
    ),
    "approaching": (
        "Glad we matched — you seem like trouble, the good kind. What's keeping "
        "you busy these days?"
    ),
    "flirting": (
        "Not gonna lie, you're a lot more fun than the app led me to believe. "
        "Dangerous."
    ),
    "banter": (
        "Bold of you to assume I'll back down from this one. Okay, one point to "
        "you — but I'm coming for it."
    ),
    "rapport-building": (
        "Okay real question: what's something you're weirdly passionate about "
        "that I'd never guess from your profile?"
    ),
    "storytelling": (
        "This reminds me — I once tried to look cool and walked straight into a "
        "glass door on a first date. Please tell me you've got a worse one."
    ),
    "proposing-a-date": (
        "This clearly needs to be settled in person. Drinks or tacos this week — "
        "say Thursday? No worries if your week's slammed."
    ),
    "number-exchange": (
        "Easier to plan off here — want to trade numbers and lock something in? "
        "No pressure either way."
    ),
    "re-engagement": (
        "Random update: I finally went back to that spot we talked about, purely "
        "for the better photo. How've you been?"
    ),
    "conversation-recovery": (
        "Okay that topic clearly peaked — my fault. New question: what's the most "
        "unreasonable hill you'll die on, food or otherwise?"
    ),
}

_GENERIC_DRAFT = (
    "Honestly really enjoying this — tell me more, I'm curious."
)


def _default_responder(messages: Sequence[Message]) -> str:
    """A deterministic, skill-aware stand-in reply for the offline stub."""
    blob = "\n".join((m.get("content") or "") for m in messages)
    last_user = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user = (msg.get("content") or "").strip()
            break
    # If a draft is explicitly delimited (style-transfer path), echo it through
    # so the offline pipeline stays coherent even when something calls the stub.
    if "<<<DRAFT>>>" in last_user and "<<<END>>>" in last_user:
        start = last_user.index("<<<DRAFT>>>") + len("<<<DRAFT>>>")
        end = last_user.index("<<<END>>>")
        return last_user[start:end].strip()
    match = re.search(r"PRIMARY_SKILL:\s*([\w-]+)", blob)
    if match:
        return _STUB_DRAFTS.get(match.group(1), _GENERIC_DRAFT)
    return _STUB_DRAFTS["opener"]


class EchoBackend:
    """A deterministic, offline backend for ``--mock`` runs and tests."""

    def __init__(
        self, responder: Callable[[Sequence[Message]], str] | None = None
    ) -> None:
        self.responder = responder or _default_responder

    def complete(
        self,
        resolved: ResolvedModel,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> LLMResult:
        text = self.responder(messages)
        return LLMResult(
            text=text,
            provider=resolved.provider,
            model=resolved.model,
            raw=None,
        )

    def stream(
        self,
        resolved: ResolvedModel,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> Iterator[str]:
        yield self.responder(messages)


class LLMRouter:
    """Routes completions across an ordered list of provider/model selections."""

    def __init__(
        self,
        backend: LLMBackend,
        selections: Sequence[ResolvedModel],
        *,
        temperature: float | None = 0.8,
        max_tokens: int | None = 600,
        max_retries: int = 2,
        retry_backoff: float = 0.5,
        timeout: float | None = 60.0,
        is_stub: bool = False,
    ) -> None:
        if not selections:
            raise ValueError("LLMRouter requires at least one model selection")
        self.backend = backend
        self.selections = list(selections)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.timeout = timeout
        self.is_stub = is_stub
        # Cumulative token/usage accounting across the router's lifetime.
        self.usage: dict[str, int] = {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def _record_usage(self, result: LLMResult) -> None:
        self.usage["calls"] += 1
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if result.usage and key in result.usage:
                self.usage[key] += int(result.usage[key])
        if result.usage:
            log.debug(
                "LLM usage provider=%s model=%s tokens=%s (cumulative total=%d)",
                result.provider,
                result.model,
                result.usage,
                self.usage["total_tokens"],
            )

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def from_config(
        cls,
        llm_config: "LLMConfigLike",
        secrets: Mapping[str, str | None] | None = None,
        *,
        stub: bool = False,
    ) -> "LLMRouter":
        """Build a router from an LLM config object + a secrets mapping."""
        selections: list[ResolvedModel] = [
            resolve_model(llm_config.provider, llm_config.model, secrets)
        ]
        for fb in getattr(llm_config, "fallbacks", []) or []:
            selections.append(resolve_model(fb.provider, fb.model, secrets))

        for sel in selections:
            register_secret(sel.api_key)

        backend: LLMBackend = EchoBackend() if stub else LiteLLMBackend()
        return cls(
            backend,
            selections,
            temperature=getattr(llm_config, "temperature", 0.8),
            max_tokens=getattr(llm_config, "max_tokens", 600),
            max_retries=getattr(llm_config, "max_retries", 2),
            timeout=getattr(llm_config, "timeout", 60.0),
            is_stub=stub,
        )

    def ensure_ready(self, secrets: Mapping[str, str | None] | None = None) -> None:
        """Raise a helpful error if the primary provider has no credentials."""
        if self.is_stub:
            return
        primary = self.selections[0]
        if not provider_ready(primary.provider, secrets):
            raise RuntimeError(
                f"No credentials found for provider {primary.provider!r}. "
                "Set the required environment variable (see `opendate providers`) "
                "or run with --mock to use the offline stub LLM."
            )

    # ------------------------------------------------------------------ #
    # Completion
    # ------------------------------------------------------------------ #
    def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        temperature = self.temperature if temperature is None else temperature
        max_tokens = self.max_tokens if max_tokens is None else max_tokens
        last_error: Exception | None = None
        for index, selection in enumerate(self.selections):
            for attempt in range(1, self.max_retries + 1):
                try:
                    result = self.backend.complete(
                        selection,
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=self.timeout,
                    )
                    self._record_usage(result)
                    return result
                except Exception as exc:  # noqa: BLE001 - we retry/fall back
                    last_error = exc
                    log.warning(
                        "LLM call failed (provider=%s attempt=%d/%d): %s",
                        selection.provider,
                        attempt,
                        self.max_retries,
                        exc,
                    )
                    if attempt < self.max_retries:
                        # Exponential backoff: backoff, 2x, 4x, ... (+ jitter).
                        delay = self.retry_backoff * (2 ** (attempt - 1))
                        if delay > 0:
                            time.sleep(delay)
            if index < len(self.selections) - 1:
                log.info(
                    "Falling back from %s to %s",
                    selection.provider,
                    self.selections[index + 1].provider,
                )
        raise RuntimeError(
            f"All LLM selections failed; last error: {last_error}"
        ) from last_error

    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
        """Stream tokens from the *primary* selection (no fallback mid-stream)."""
        yield from self.backend.stream(
            self.selections[0],
            messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Convenience: single system + user turn, returns the text."""
        messages: list[Message] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        return self.complete(
            messages, temperature=temperature, max_tokens=max_tokens
        ).text

    # ------------------------------------------------------------------ #
    # Structured JSON (request + parse, with a safe fallback)
    # ------------------------------------------------------------------ #
    def complete_json(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        default: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Run a completion and parse the reply as JSON (``default`` on failure)."""
        try:
            result = self.complete(
                messages, temperature=temperature, max_tokens=max_tokens
            )
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            log.warning("complete_json failed: %s", exc)
            return default
        parsed = extract_json(result.text)
        return parsed if parsed is not None else default

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        default: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Convenience JSON variant of :meth:`chat` with a safe fallback."""
        messages: list[Message] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        return self.complete_json(
            messages, temperature=temperature, max_tokens=max_tokens, default=default
        )

    # ------------------------------------------------------------------ #
    # Async variants (used by the orchestrator)
    # ------------------------------------------------------------------ #
    async def acomplete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        return await asyncio.to_thread(
            self.complete,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def achat(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self.chat,
            system,
            user,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @property
    def primary_label(self) -> str:
        sel = self.selections[0]
        return f"{sel.provider}:{sel.model}"


# A tiny structural type so ``from_config`` doesn't import the config module
# (avoids a circular import) while still documenting what it expects.
class LLMConfigLike(Protocol):  # pragma: no cover - typing only
    provider: str
    model: str | None
    fallbacks: Iterable["LLMConfigLike"]
    temperature: float | None
    max_tokens: int | None
    max_retries: int
    timeout: float | None
