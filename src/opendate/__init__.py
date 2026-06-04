"""OpenDate — a vibe-dating AI agent.

OpenDate screens potential dates against your preferences, opens and carries
conversations using purpose-built dating *skills*, and rewrites every outgoing
message in a persona learned from your own social posts and chats — with
consent guardrails and optional human approval before anything is sent.

The public surface is intentionally small; most work happens through the CLI
(``python -m opendate ...``) or by composing the modules directly:

    from opendate.config import load_config
    from opendate.connectors.mock import MockConnector
    from opendate.skills.engine import SkillsEngine
    from opendate.orchestrator.loop import Orchestrator
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
