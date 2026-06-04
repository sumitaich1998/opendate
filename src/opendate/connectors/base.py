"""The match-source interface and the data models that flow through OpenDate.

Both the real Tinder connector and the offline mock implement
:class:`MatchSource`, so the orchestrator never knows (or cares) which one it is
talking to. All methods are ``async``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import AppConfig, Secrets

__all__ = [
    "Sender",
    "Message",
    "Candidate",
    "Match",
    "MatchSource",
    "build_connector",
]

Sender = Literal["me", "them"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Message(BaseModel):
    """A single chat message within a match thread."""

    id: str
    match_id: str
    sender: Sender
    text: str
    sent_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @property
    def from_me(self) -> bool:
        return self.sender == "me"


class Candidate(BaseModel):
    """A potential date (a recommendation), before any like/pass decision."""

    id: str
    name: str = ""
    age: int | None = None
    bio: str = ""
    distance_km: float | None = None
    photos: list[str] = Field(default_factory=list)
    prompts: dict[str, str] = Field(default_factory=dict)
    interests: list[str] = Field(default_factory=list)
    jobs: list[str] = Field(default_factory=list)
    schools: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    def profile_text(self) -> str:
        """A compact, prompt-friendly rendering of the profile."""
        parts: list[str] = []
        header = self.name or "(no name)"
        if self.age:
            header += f", {self.age}"
        parts.append(header)
        if self.distance_km is not None:
            parts.append(f"~{round(self.distance_km)} km away")
        if self.jobs:
            parts.append("Work: " + ", ".join(self.jobs))
        if self.schools:
            parts.append("School: " + ", ".join(self.schools))
        if self.bio:
            parts.append(f"Bio: {self.bio}")
        if self.interests:
            parts.append("Interests: " + ", ".join(self.interests))
        for q, a in self.prompts.items():
            parts.append(f"{q}: {a}")
        return "\n".join(parts)


class Match(BaseModel):
    """A mutual match — someone you can message."""

    id: str
    person_id: str = ""
    name: str = ""
    photos: list[str] = Field(default_factory=list)
    bio: str = ""
    created_at: datetime | None = None
    last_activity_at: datetime | None = None
    messages: list[Message] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @property
    def has_messages(self) -> bool:
        return bool(self.messages)

    @property
    def last_message(self) -> Message | None:
        return self.messages[-1] if self.messages else None

    @property
    def awaiting_their_reply(self) -> bool:
        """True if the most recent message was from us (we're waiting on them)."""
        last = self.last_message
        return last is not None and last.from_me


@runtime_checkable
class MatchSource(Protocol):
    """The interface every connector implements (async)."""

    async def get_recommendations(self, limit: int = 10) -> list[Candidate]:
        """Fetch potential dates to screen."""
        ...

    async def like(self, candidate_id: str) -> dict[str, Any]:
        """Like a candidate. Returns provider response (may include a match)."""
        ...

    async def pass_(self, candidate_id: str) -> dict[str, Any]:
        """Pass on a candidate."""
        ...

    async def get_matches(self, count: int = 60) -> list[Match]:
        """List current matches."""
        ...

    async def get_messages(self, match_id: str, count: int = 100) -> list[Message]:
        """Read messages for a match (oldest -> newest)."""
        ...

    async def send_message(self, match_id: str, text: str) -> Message:
        """Send a message to a match."""
        ...

    async def close(self) -> None:
        """Release any underlying resources (e.g. HTTP client)."""
        ...


def build_connector(
    config: "AppConfig",
    secrets: "Secrets | None" = None,
    *,
    force_mock: bool = False,
) -> MatchSource:
    """Construct the connector named by ``config.source`` (or the mock).

    ``force_mock`` (set by the CLI ``--mock`` flag) always returns the offline
    :class:`~opendate.connectors.mock.MockConnector` so OpenDate is demoable and
    testable with zero real credentials.
    """
    if force_mock or config.source == "mock":
        from .mock import MockConnector

        return MockConnector()

    from .tinder import TinderConnector

    token = secrets.tinder_auth_token if secrets else None
    if not token:
        raise RuntimeError(
            "No TINDER_AUTH_TOKEN found. Set it in your environment/.env, "
            "or run with --mock to use the offline demo connector."
        )
    return TinderConnector(auth_token=token)
