"""Config + secrets tests (offline)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opendate.config import (
    AgeRange,
    AppConfig,
    PersonaBlend,
    Preferences,
    RelationshipIntent,
    Secrets,
    load_config,
)


def test_load_config_from_yaml(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
source: mock
auto_send: true
preferences:
  looking_for: long-term
  partner_traits: witty, outdoorsy, ambitious
  dealbreakers: [smoking]
  age_range: {min: 26, max: 34}
  distance_km: 25
llm:
  provider: deepseek
  model: deepseek-chat
""",
        encoding="utf-8",
    )
    config = load_config(cfg)
    assert config.source == "mock"
    assert config.auto_send is True
    assert config.preferences.looking_for is RelationshipIntent.LONG_TERM
    # Comma-separated string is coerced to a list.
    assert config.preferences.partner_traits == ["witty", "outdoorsy", "ambitious"]
    assert config.preferences.age_range.min == 26
    assert config.llm.provider == "deepseek"


def test_defaults_when_no_config():
    config = load_config(None)
    assert isinstance(config, AppConfig)
    assert config.auto_send is False


def test_invalid_source_rejected():
    with pytest.raises(ValidationError):
        AppConfig(source="hinge")


def test_unknown_provider_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"llm": {"provider": "not-a-provider"}})


def test_age_range_validation():
    with pytest.raises(ValidationError):
        AgeRange(min=40, max=20)
    rng = AgeRange(min=26, max=34)
    assert rng.contains(30)
    assert not rng.contains(50)
    assert rng.contains(None)  # unknown age isn't a hard fail


def test_persona_blend_normalizes():
    blend = PersonaBlend(social_posts=4, past_chats=3.5, stated_preferences=2.5)
    total = blend.social_posts + blend.past_chats + blend.stated_preferences
    assert total == pytest.approx(1.0)


def test_preferences_csv_coercion():
    prefs = Preferences(dealbreakers="smoking, ghosting")
    assert prefs.dealbreakers == ["smoking", "ghosting"]


def test_secrets_env_map_and_redaction(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-1234567890")
    monkeypatch.setenv("TINDER_AUTH_TOKEN", "tinder-secret-token")
    secrets = Secrets()
    env_map = secrets.env_map()
    assert env_map["OPENAI_API_KEY"] == "sk-test-1234567890"
    assert "DEEPSEEK_API_KEY" in env_map  # every provider env var is present
    # Registering for redaction should mask the value in logs.
    from opendate.utils.logging import redact

    secrets.register_for_redaction()
    assert "sk-test-1234567890" not in redact("key is sk-test-1234567890")
