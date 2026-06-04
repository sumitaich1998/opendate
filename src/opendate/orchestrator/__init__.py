"""The orchestrator: OpenDate's brain.

Runs the async runtime loop — Sync -> Screen -> Decide -> Generate -> Voice ->
Guard -> Act — across all matches, gating risky steps behind the safety guard
and (optionally) human approval.
"""

from __future__ import annotations

from .loop import Orchestrator, PlannedAction, build_situation, score_candidate
from .safety import SafetyDecision, SafetyGuard

__all__ = [
    "Orchestrator",
    "PlannedAction",
    "build_situation",
    "score_candidate",
    "SafetyGuard",
    "SafetyDecision",
]
