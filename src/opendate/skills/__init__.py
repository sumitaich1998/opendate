"""The OpenDate skills engine.

Skills are authored in the `agentskills.io <https://agentskills.io>`_ standard:
one folder per skill containing a ``SKILL.md`` with YAML frontmatter
(``name`` + ``description`` + optional ``when_to_use``) followed by a markdown
playbook body. :class:`~opendate.skills.engine.SkillsEngine` discovers them,
exposes them, and selects the right one for a given conversation moment.
"""

from __future__ import annotations

from .engine import (
    ALWAYS_ACTIVE,
    Skill,
    SkillSelection,
    SkillsEngine,
    SituationContext,
)

__all__ = [
    "Skill",
    "SkillSelection",
    "SkillsEngine",
    "SituationContext",
    "ALWAYS_ACTIVE",
]
