"""Ingest the user's writing samples (social posts + past chats).

Supports plain text (one item per line) and JSON. Chat exports are filtered down
to *the user's own lines* using ``my_names`` so the persona reflects the user,
not the people they talked to. Missing files are skipped (with a warning) so the
engine degrades gracefully.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..utils.logging import get_logger

__all__ = ["Sample", "IngestResult", "ingest_sources", "ingest_paths"]

log = get_logger("persona.ingest")

# Sender labels that are treated as "the user" when no explicit names are given.
_SELF_ALIASES = {"me", "self", "you", "user", "sent", "outgoing"}


@dataclass
class Sample:
    """One writing sample attributed to the user."""

    text: str
    source: str  # "social_post" | "chat"


@dataclass
class IngestResult:
    """The collected samples, split by source."""

    social_posts: list[str] = field(default_factory=list)
    chat_messages: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def all_texts(self) -> list[str]:
        return self.social_posts + self.chat_messages

    @property
    def total(self) -> int:
        return len(self.social_posts) + len(self.chat_messages)

    def samples(self) -> list[Sample]:
        return [Sample(t, "social_post") for t in self.social_posts] + [
            Sample(t, "chat") for t in self.chat_messages
        ]


def _clean(text: Any) -> str:
    return str(text).strip() if text is not None else ""


def _is_self(sender: Any, my_names: Iterable[str]) -> bool:
    sender_l = _clean(sender).lower()
    if not sender_l:
        return True  # unattributed line in an export: assume it's the user's
    names = {n.lower() for n in my_names if n}
    if sender_l in names or any(n and n in sender_l for n in names):
        return True
    return sender_l in _SELF_ALIASES


def _extract_texts_from_json(data: Any, my_names: Iterable[str]) -> tuple[list[str], bool]:
    """Return (texts, looked_like_chat). Handles several common shapes."""
    looked_like_chat = False

    if isinstance(data, dict) and "messages" in data:
        data = data["messages"]

    texts: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                if _clean(item):
                    texts.append(_clean(item))
            elif isinstance(item, dict):
                text = _clean(
                    item.get("text")
                    or item.get("message")
                    or item.get("content")
                    or item.get("body")
                )
                if not text:
                    continue
                sender = (
                    item.get("sender")
                    or item.get("from")
                    or item.get("author")
                    or item.get("user")
                    or item.get("name")
                )
                if sender is not None:
                    looked_like_chat = True
                    if _is_self(sender, my_names):
                        texts.append(text)
                else:
                    texts.append(text)
    elif isinstance(data, str):
        if _clean(data):
            texts.append(_clean(data))
    return texts, looked_like_chat


def ingest_paths(
    paths: Iterable[str | Path],
    *,
    kind: str,
    my_names: Iterable[str] = (),
) -> tuple[list[str], list[str]]:
    """Read every path; return (texts, skipped_paths)."""
    texts: list[str] = []
    skipped: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            log.warning("Persona source not found, skipping: %s", path)
            skipped.append(str(path))
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("Could not read %s: %s", path, exc)
            skipped.append(str(path))
            continue

        if path.suffix.lower() == ".json":
            try:
                data = json.loads(content)
            except json.JSONDecodeError as exc:
                log.warning("Invalid JSON in %s: %s", path, exc)
                skipped.append(str(path))
                continue
            file_texts, _ = _extract_texts_from_json(data, my_names)
            texts.extend(file_texts)
        else:
            # Plain text: one post/message per non-empty line.
            for line in content.splitlines():
                cleaned = _clean(line)
                if cleaned:
                    texts.append(cleaned)
    return texts, skipped


def ingest_sources(sources: "PersonaSourcesLike") -> IngestResult:
    """Ingest the configured persona sources into an :class:`IngestResult`."""
    my_names = list(getattr(sources, "my_names", []) or [])
    posts, skipped_a = ingest_paths(
        getattr(sources, "social_posts", []) or [],
        kind="social_post",
        my_names=my_names,
    )
    chats, skipped_b = ingest_paths(
        getattr(sources, "chat_history", []) or [],
        kind="chat",
        my_names=my_names,
    )
    result = IngestResult(
        social_posts=posts,
        chat_messages=chats,
        skipped=skipped_a + skipped_b,
    )
    log.info(
        "Ingested %d social posts and %d chat messages (%d sources skipped)",
        len(result.social_posts),
        len(result.chat_messages),
        len(result.skipped),
    )
    return result


# Structural typing to avoid importing config (no circular import).
class PersonaSourcesLike:  # pragma: no cover - typing only
    social_posts: list[str]
    chat_history: list[str]
    my_names: list[str]
