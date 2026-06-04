"""Match-source connectors.

Everything OpenDate does against a dating app goes through the
:class:`~opendate.connectors.base.MatchSource` interface, so the real
:class:`~opendate.connectors.tinder.TinderConnector` and the offline
:class:`~opendate.connectors.mock.MockConnector` are fully interchangeable.
"""

from __future__ import annotations

from .base import Candidate, Match, MatchSource, Message, build_connector
from .mock import MockConnector

__all__ = [
    "Candidate",
    "Match",
    "Message",
    "MatchSource",
    "MockConnector",
    "build_connector",
]
