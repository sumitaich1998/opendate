"""Personality engine: ingest, analyze, and style transfer (offline)."""

from __future__ import annotations

import json

from opendate.persona.analyze import PersonaProfile, analyze_persona, load_profile
from opendate.persona.ingest import IngestResult, ingest_paths
from opendate.persona.style import StyleTransfer


def test_ingest_plain_text(tmp_path):
    f = tmp_path / "posts.txt"
    f.write_text("first post\n\nsecond post\n", encoding="utf-8")
    texts, skipped = ingest_paths([f], kind="social_post")
    assert texts == ["first post", "second post"]
    assert not skipped


def test_ingest_chat_json_filters_by_name(tmp_path):
    f = tmp_path / "chat.json"
    f.write_text(
        json.dumps(
            [
                {"sender": "Me", "text": "mine one"},
                {"sender": "Them", "text": "theirs"},
                {"sender": "me", "text": "mine two"},
            ]
        ),
        encoding="utf-8",
    )
    texts, _ = ingest_paths([f], kind="chat", my_names=["me"])
    assert texts == ["mine one", "mine two"]


def test_ingest_missing_file_is_skipped(tmp_path):
    texts, skipped = ingest_paths([tmp_path / "nope.txt"], kind="chat")
    assert texts == []
    assert len(skipped) == 1


def test_analyze_metrics():
    ingest = IngestResult(
        social_posts=["lol this is great 😄", "coffee snob alert ☕"],
        chat_messages=["haha yeah totally", "ngl that's a great take"],
    )
    profile = analyze_persona(ingest, voice="warm, sarcastic", router=None)
    assert profile.emoji_rate > 0
    assert "😄" in profile.emojis or "☕" in profile.emojis
    assert any(s in profile.slang for s in ("lol", "haha", "ngl"))
    assert profile.avg_message_words > 0
    assert profile.tone == "warm, sarcastic"
    assert not profile.generated_with_llm  # no LLM used


def test_analyze_degrades_without_samples():
    profile = analyze_persona(IngestResult(), voice="dry and witty", router=None)
    assert isinstance(profile, PersonaProfile)
    assert profile.tone == "dry and witty"


def test_style_transfer_heuristic_lowercase_and_emoji():
    persona = PersonaProfile(lowercase_ratio=0.9, emoji_rate=0.8, emojis=["😄"])
    st = StyleTransfer(router=None)
    out = st.transfer("Hello There! How Are You", persona)
    assert out.lower() == out  # lowercased
    assert "😄" in out  # emoji appended for an emoji-heavy persona


def test_style_transfer_strips_emoji_for_plain_persona():
    persona = PersonaProfile(emoji_rate=0.0)
    st = StyleTransfer(router=None)
    out = st.transfer("nice to meet you 😄🌮", persona)
    assert "😄" not in out and "🌮" not in out


def test_profile_save_load(tmp_path):
    persona = PersonaProfile(tone="warm", slang=["lol"], emojis=["😄"])
    path = persona.save(tmp_path / "persona.json")
    loaded = load_profile(path)
    assert loaded.tone == "warm"
    assert loaded.slang == ["lol"]


def test_style_brief_contains_signals():
    persona = PersonaProfile(
        tone="warm", humor_style="dry", slang=["lol"], vocabulary=["climbing"]
    )
    brief = persona.style_brief()
    assert "Tone: warm" in brief
    assert "climbing" in brief


def test_persona_exemplars_selected():
    ingest = IngestResult(
        social_posts=["coffee snob alert, judging your order ☕"],
        chat_messages=[
            "ngl you're funnier than i expected, what's your go-to karaoke song?",
            "haha okay that's a great take",
        ],
    )
    profile = analyze_persona(ingest, voice="warm", router=None)
    assert profile.exemplars
    # The slang + question-bearing chat line should rank as the top exemplar.
    assert "karaoke" in profile.exemplars[0]


def test_voice_card_is_compact_and_informative():
    profile = PersonaProfile(
        tone="warm, sarcastic",
        humor_style="dry",
        slang=["lol", "ngl"],
        emojis=["☕"],
        avg_message_words=9,
    )
    card = profile.voice_card()
    assert "Tone" in card and "warm, sarcastic" in card
    # Compact: a handful of lines, not the full brief.
    assert len(card.splitlines()) <= 7


def test_exemplar_block_falls_back_to_samples():
    profile = PersonaProfile(sample_messages=["hi there friend, good to meet you"])
    assert "hi there friend" in profile.exemplar_block()
