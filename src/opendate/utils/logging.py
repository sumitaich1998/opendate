"""Logging setup for OpenDate.

Two hard rules drive this module:

1. **Secrets are never logged.** A :class:`RedactingFilter` scrubs anything that
   looks like an API key / auth token from every log record before it is
   emitted, and :func:`register_secret` lets the config layer register the exact
   secret values it loaded so they are masked even if they slip into a message.
2. **Output is pretty.** We use :class:`rich.logging.RichHandler` so the CLI
   experience matches the rest of OpenDate.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from rich.console import Console
from rich.logging import RichHandler

__all__ = [
    "get_console",
    "get_logger",
    "configure_logging",
    "register_secret",
    "redact",
]

# A shared console so log output and ``rich`` UI share one render pipeline.
_CONSOLE = Console(stderr=True)

# Exact secret values registered at runtime (e.g. the loaded Tinder token).
_KNOWN_SECRETS: set[str] = set()

# Heuristic patterns for things that look like secrets even if not registered.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Common provider key prefixes: sk-..., sk-ant-..., gsk_..., xai-..., AIza...
    re.compile(r"\b(sk-ant-[A-Za-z0-9_\-]{8,})", re.IGNORECASE),
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{12,})", re.IGNORECASE),
    re.compile(r"\b(gsk_[A-Za-z0-9_\-]{12,})", re.IGNORECASE),
    re.compile(r"\b(xai-[A-Za-z0-9_\-]{12,})", re.IGNORECASE),
    re.compile(r"\b(AIza[0-9A-Za-z_\-]{20,})"),
    # key=value / "token": "value" style assignments for known secret names.
    re.compile(
        r"((?:auth[_-]?token|api[_-]?key|x-auth-token|secret|password)"
        r"['\"]?\s*[:=]\s*['\"]?)([^\s'\",}]{6,})",
        re.IGNORECASE,
    ),
)

_MASK = "***REDACTED***"


def register_secret(value: str | None) -> None:
    """Register a concrete secret value so it is masked everywhere in logs."""
    if value and isinstance(value, str) and len(value) >= 4:
        _KNOWN_SECRETS.add(value)


def redact(text: str) -> str:
    """Return ``text`` with any known or secret-looking substrings masked."""
    if not text:
        return text
    for secret in _KNOWN_SECRETS:
        if secret in text:
            text = text.replace(secret, _MASK)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: f"{m.group(1)}{_MASK}", text)
        else:
            text = pattern.sub(_MASK, text)
    return text


class RedactingFilter(logging.Filter):
    """A logging filter that redacts secrets from the rendered message."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def get_console() -> Console:
    """Return the shared :class:`rich.console.Console` (stderr)."""
    return _CONSOLE


def configure_logging(level: int | str = logging.INFO) -> None:
    """Install a rich, secret-redacting handler on the ``opendate`` logger."""
    logger = logging.getLogger("opendate")
    logger.setLevel(level)
    logger.handlers.clear()
    handler = RichHandler(
        console=_CONSOLE,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        markup=False,
    )
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str = "opendate") -> logging.Logger:
    """Return a namespaced child logger that inherits the redacting handler."""
    if not name.startswith("opendate"):
        name = f"opendate.{name}"
    logger = logging.getLogger(name)
    if not logging.getLogger("opendate").handlers:
        configure_logging()
    return logger


def register_secrets(values: Iterable[str | None]) -> None:
    """Convenience: register many secret values at once."""
    for value in values:
        register_secret(value)
