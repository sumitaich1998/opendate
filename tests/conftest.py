"""Shared, fully-offline pytest fixtures.

Every fixture here avoids the network: the connector is the in-memory mock and
the LLM is the deterministic :class:`EchoBackend` stub.
"""

from __future__ import annotations

import pytest

from opendate.config import AppConfig, LLMConfig, Preferences, SafetyConfig
from opendate.connectors.mock import MockConnector
from opendate.llm.router import EchoBackend, LLMRouter
from opendate.llm.providers import resolve_model
from opendate.persona.analyze import analyze_persona
from opendate.persona.ingest import IngestResult
from opendate.skills.engine import SkillsEngine


@pytest.fixture
def skills_engine() -> SkillsEngine:
    engine = SkillsEngine()
    engine.load_all()
    return engine


@pytest.fixture
def mock_connector() -> MockConnector:
    return MockConnector()


@pytest.fixture
def stub_router() -> LLMRouter:
    return LLMRouter.from_config(
        LLMConfig(provider="openai", model="gpt-4o-mini"), {}, stub=True
    )


def make_stub_router(responder=None) -> LLMRouter:
    backend = EchoBackend(responder=responder)
    selection = resolve_model("openai", "gpt-4o-mini", {})
    return LLMRouter(backend, [selection], is_stub=True)


@pytest.fixture
def persona():
    ingest = IngestResult(
        social_posts=[
            "just sent my hardest boulder lol knees are jelly",
            "coffee snob alert, judging your order rn",
        ],
        chat_messages=[
            "haha okay that is actually a great take",
            "ngl you're funnier than i expected",
        ],
    )
    return analyze_persona(ingest, voice="warm, a little sarcastic", router=None)


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig(
        source="mock",
        auto_send=False,
        preferences=Preferences(
            partner_traits=["witty", "outdoorsy"],
            dealbreakers=["smoking"],
            interests=["climbing", "live music"],
        ),
        llm=LLMConfig(provider="openai", model="gpt-4o-mini"),
        safety=SafetyConfig(),
    )
