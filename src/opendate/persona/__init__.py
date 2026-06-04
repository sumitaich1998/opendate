"""The Personality Engine.

Learns the user's voice from their social posts and past chats, builds a
:class:`~opendate.persona.analyze.PersonaProfile`, and rewrites outgoing
messages so they sound like the user (style transfer). It combines LLM-based
extraction with simple heuristics so it **degrades gracefully without an LLM**.
"""

from __future__ import annotations

from .analyze import PersonaProfile, analyze_persona, build_persona
from .ingest import IngestResult, Sample, ingest_sources
from .style import StyleTransfer

__all__ = [
    "Sample",
    "IngestResult",
    "ingest_sources",
    "PersonaProfile",
    "analyze_persona",
    "build_persona",
    "StyleTransfer",
]
