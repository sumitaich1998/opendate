"""Turn ingested writing samples into a :class:`PersonaProfile`.

The analyzer is deliberately a hybrid:

* **Heuristics** (always) measure emoji/punctuation rates, message length and
  cadence, vocabulary, slang, and go-to openers directly from the samples.
* **LLM extraction** (optional) refines tone, humor, and a natural-language
  summary — but only when a real (non-stub) router is supplied. Without it, the
  heuristics stand on their own so the engine **degrades gracefully**.

Signals from social posts, past chats, and the user's *stated* voice are blended
with configurable weights (defaulting to 40% / 35% / 25%, per the blueprint).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, Field

from ..utils.logging import get_logger

__all__ = ["PersonaProfile", "analyze_persona", "build_persona", "load_profile"]

log = get_logger("persona.analyze")

_EMOJI_RE = re.compile(
    "[" 
    "\U0001f300-\U0001fAFF"  # symbols, pictographs, emoji extensions
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0001f1e6-\U0001f1ff"  # regional indicators
    "\U00002190-\U000021ff"  # arrows (some emoji)
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U00002700-\U000027bf"
    "]",
    flags=re.UNICODE,
)

_WORD_RE = re.compile(r"[A-Za-z']+")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "to", "of", "in", "on", "for",
    "is", "are", "was", "were", "be", "been", "it", "its", "this", "that",
    "i", "im", "you", "your", "youre", "me", "my", "we", "they", "he", "she",
    "do", "did", "does", "have", "has", "had", "so", "just", "with", "as", "at",
    "not", "no", "yes", "ok", "okay", "up", "out", "about", "what", "who",
    "how", "when", "where", "why", "can", "will", "would", "should", "could",
    "get", "got", "go", "going", "like", "really", "very", "too", "all", "by",
}

_SLANG = {
    "lol", "lmao", "lmaooo", "rofl", "haha", "hahaha", "hehe", "tbh", "ngl",
    "imo", "omg", "fr", "frfr", "idk", "ikr", "smh", "bruh", "bro", "dude",
    "vibe", "vibes", "lowkey", "highkey", "deadass", "fam", "sus", "bet",
    "yeah", "yep", "nah", "gonna", "wanna", "kinda", "sorta", "ya", "u", "ur",
    "obvi", "literally", "honestly", "anyways", "wholesome", "iconic",
}


def _emojis(text: str) -> list[str]:
    return _EMOJI_RE.findall(text)


class _Metrics:
    """Aggregate measurements over a list of messages."""

    def __init__(self, texts: Sequence[str]) -> None:
        self.n = len(texts)
        self.emoji_counter: Counter[str] = Counter()
        self.token_counter: Counter[str] = Counter()
        self.slang_counter: Counter[str] = Counter()
        self.opener_counter: Counter[str] = Counter()
        words = 0
        chars = 0
        exclaim = 0
        question = 0
        ellipsis = 0
        lowercase_msgs = 0
        for text in texts:
            chars += len(text)
            found = _emojis(text)
            self.emoji_counter.update(found)
            tokens = [t.lower() for t in _WORD_RE.findall(text)]
            words += len(tokens)
            for tok in tokens:
                if tok in _SLANG:
                    self.slang_counter[tok] += 1
                if tok not in _STOPWORDS and len(tok) > 2:
                    self.token_counter[tok] += 1
            if "!" in text:
                exclaim += 1
            if "?" in text:
                question += 1
            if "..." in text or "…" in text:
                ellipsis += 1
            alpha = [c for c in text if c.isalpha()]
            if alpha and all(not c.isupper() for c in alpha):
                lowercase_msgs += 1
            # Opener = first three words, if the message starts a thought.
            opener = " ".join(tokens[:3])
            if opener:
                self.opener_counter[opener] += 1
        self.avg_words = words / self.n if self.n else 0.0
        self.avg_chars = chars / self.n if self.n else 0.0
        self.emoji_rate = sum(self.emoji_counter.values()) / self.n if self.n else 0.0
        self.exclaim_rate = exclaim / self.n if self.n else 0.0
        self.question_rate = question / self.n if self.n else 0.0
        self.ellipsis_rate = ellipsis / self.n if self.n else 0.0
        self.lowercase_ratio = lowercase_msgs / self.n if self.n else 0.0


class PersonaProfile(BaseModel):
    """A learned model of the user's texting voice."""

    tone: str = "warm and curious"
    summary: str = ""
    humor_style: str = "lightly playful"
    cadence: str = "medium-length texts"

    vocabulary: list[str] = Field(default_factory=list)
    slang: list[str] = Field(default_factory=list)
    emojis: list[str] = Field(default_factory=list)
    go_to_openers: list[str] = Field(default_factory=list)

    emoji_rate: float = 0.0
    exclamation_rate: float = 0.0
    question_rate: float = 0.0
    ellipsis_user: bool = False
    lowercase_ratio: float = 0.0
    avg_message_words: float = 0.0
    avg_message_chars: float = 0.0

    sample_messages: list[str] = Field(default_factory=list)
    exemplars: list[str] = Field(
        default_factory=list,
        description="Representative real messages used as few-shot voice examples.",
    )
    sources: dict[str, int] = Field(default_factory=dict)
    blend: dict[str, float] = Field(default_factory=dict)
    generated_with_llm: bool = False

    def style_brief(self) -> str:
        """A compact, prompt-ready description of the user's voice."""
        lines = [
            f"Tone: {self.tone}",
            f"Humor: {self.humor_style}",
            f"Cadence: {self.cadence} (~{self.avg_message_words:.0f} words/msg)",
        ]
        if self.emojis:
            freq = (
                "rarely" if self.emoji_rate < 0.2
                else "often" if self.emoji_rate >= 1 else "sometimes"
            )
            lines.append(f"Emoji: uses {freq} — favorites: {' '.join(self.emojis[:6])}")
        else:
            lines.append("Emoji: rarely/never")
        punct = []
        if self.lowercase_ratio > 0.5:
            punct.append("often lowercase")
        if self.ellipsis_user:
            punct.append("uses ellipses…")
        if self.exclamation_rate > 0.5:
            punct.append("fond of exclamation points")
        if punct:
            lines.append("Punctuation: " + ", ".join(punct))
        if self.slang:
            lines.append("Slang/filler: " + ", ".join(self.slang[:8]))
        if self.vocabulary:
            lines.append("Characteristic words: " + ", ".join(self.vocabulary[:10]))
        if self.go_to_openers:
            lines.append("Go-to openers: " + "; ".join(self.go_to_openers[:4]))
        if self.sample_messages:
            samples = " | ".join(self.sample_messages[:3])
            lines.append(f"Sample lines: {samples}")
        return "\n".join(lines)

    def voice_card(self) -> str:
        """A compact, at-a-glance summary of the user's texting voice."""
        emoji_freq = (
            "rarely"
            if self.emoji_rate < 0.2
            else "often"
            if self.emoji_rate >= 1
            else "sometimes"
        )
        case = "lowercase" if self.lowercase_ratio > 0.5 else "normal case"
        lines = [
            f"🗣  Tone: {self.tone}",
            f"😄  Humor: {self.humor_style}",
            f"✍️  Cadence: {self.cadence} (~{self.avg_message_words:.0f} words)",
            f"#️⃣  Emoji: {emoji_freq}"
            + (f" ({' '.join(self.emojis[:5])})" if self.emojis else "")
            + f"; {case}",
        ]
        if self.slang:
            lines.append("💬  Says: " + ", ".join(self.slang[:6]))
        if self.exemplars:
            lines.append("⭐  Sounds like: " + self.exemplars[0])
        return "\n".join(lines)

    def exemplar_block(self, limit: int = 4) -> str:
        """Few-shot examples of the user's real voice for prompting."""
        picks = self.exemplars or self.sample_messages
        if not picks:
            return ""
        return "\n".join(f"- {ex}" for ex in picks[:limit])

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path


def load_profile(path: str | Path) -> PersonaProfile:
    """Load a previously saved persona profile from JSON."""
    return PersonaProfile.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _weighted(values: dict[str, float], weights: dict[str, float]) -> float:
    total_w = sum(weights.get(k, 0.0) for k in values)
    if total_w <= 0:
        return 0.0
    return sum(v * weights.get(k, 0.0) for k, v in values.items()) / total_w


def _merge_counter(
    counters: dict[str, Counter[str]], weights: dict[str, float]
) -> Counter[str]:
    merged: Counter[str] = Counter()
    for key, counter in counters.items():
        w = weights.get(key, 0.0)
        if w <= 0 or not counter:
            continue
        for item, count in counter.items():
            merged[item] += count * w
    return merged


def _humor_from_metrics(metrics: _Metrics | None, voice: str) -> str:
    descriptors: list[str] = []
    voice_l = (voice or "").lower()
    for word in ("sarcastic", "dry", "witty", "goofy", "deadpan", "playful", "warm"):
        if word in voice_l:
            descriptors.append(word)
    if metrics:
        if metrics.slang_counter.get("lol", 0) + metrics.slang_counter.get(
            "haha", 0
        ) + metrics.slang_counter.get("lmao", 0) > 0:
            descriptors.append("playful")
        if metrics.ellipsis_rate > 0.4 and metrics.emoji_rate < 0.3:
            descriptors.append("dry, understated")
        if metrics.exclaim_rate > 0.6:
            descriptors.append("enthusiastic")
    # de-dup, keep order
    seen: list[str] = []
    for d in descriptors:
        if d not in seen:
            seen.append(d)
    return ", ".join(seen) if seen else "lightly playful"


def _cadence(avg_words: float) -> str:
    if avg_words and avg_words < 12:
        return "short, punchy texts"
    if avg_words and avg_words < 25:
        return "medium-length texts"
    if avg_words:
        return "longer, detailed texts"
    return "medium-length texts"


def _pick_exemplars(
    chats: Sequence[str],
    social: Sequence[str],
    *,
    slang: Sequence[str],
    emojis: Sequence[str],
    limit: int = 5,
) -> list[str]:
    """Choose representative real messages to use as few-shot voice examples.

    Prefers conversational chat lines, of a texty length (3-30 words), and
    rewards lines that carry the user's signature slang/emoji. Falls back to
    social posts when there aren't enough chats. Fully deterministic.
    """
    slang_set = {s.lower() for s in slang}
    emoji_set = set(emojis)

    def score(text: str) -> float:
        words = text.split()
        n = len(words)
        if n < 3 or n > 40:
            return -1.0
        s = 1.0
        if 5 <= n <= 22:  # the conversational sweet spot
            s += 0.5
        lowered = text.lower()
        if any(tok in slang_set for tok in (w.strip(".,!?") for w in lowered.split())):
            s += 0.6
        if any(e in text for e in emoji_set):
            s += 0.4
        if "?" in text:  # asks a question — engaging
            s += 0.2
        return s

    seen: set[str] = set()
    ranked: list[tuple[float, int, str]] = []
    # ``order`` keeps the sort stable & favours chats over social posts.
    for order, text in enumerate([*chats, *social]):
        key = " ".join(text.lower().split())
        if key in seen:
            continue
        seen.add(key)
        value = score(text)
        if value > 0:
            ranked.append((value, order, text))
    ranked.sort(key=lambda t: (-t[0], t[1]))
    return [text for _, _, text in ranked[:limit]]


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    fence = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not fence:
        return None
    try:
        data = json.loads(fence.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _llm_refine(
    profile: PersonaProfile, texts: Sequence[str], router: Any | None
) -> PersonaProfile:
    if router is None or getattr(router, "is_stub", False):
        return profile
    if not texts:
        return profile
    sample = "\n".join(f"- {t}" for t in texts[:40])
    system = (
        "You analyze a person's writing samples and extract their texting style. "
        "Respond ONLY with compact JSON."
    )
    user = (
        "Here are writing samples from one person:\n"
        f"{sample}\n\n"
        "Return JSON with keys: tone (short phrase), humor_style (short phrase), "
        "vocabulary (list of up to 10 characteristic words), slang (list), "
        "summary (1-2 sentence description of how they text)."
    )
    try:
        raw = router.chat(system, user, temperature=0.3, max_tokens=400)
    except Exception as exc:  # noqa: BLE001 - LLM is optional; heuristics stand
        log.warning("LLM persona refinement failed, using heuristics only: %s", exc)
        return profile
    data = _extract_json(raw)
    if not data:
        return profile
    updates: dict[str, Any] = {}
    if isinstance(data.get("tone"), str):
        updates["tone"] = data["tone"].strip()
    if isinstance(data.get("humor_style"), str):
        updates["humor_style"] = data["humor_style"].strip()
    if isinstance(data.get("summary"), str):
        updates["summary"] = data["summary"].strip()
    if isinstance(data.get("vocabulary"), list):
        merged = list(
            dict.fromkeys([*map(str, data["vocabulary"]), *profile.vocabulary])
        )
        updates["vocabulary"] = merged[:12]
    if isinstance(data.get("slang"), list):
        merged = list(dict.fromkeys([*map(str, data["slang"]), *profile.slang]))
        updates["slang"] = merged[:12]
    updates["generated_with_llm"] = True
    return profile.model_copy(update=updates)


def analyze_persona(
    ingest: "IngestResultLike",
    *,
    voice: str = "",
    blend: dict[str, float] | None = None,
    router: Any | None = None,
) -> PersonaProfile:
    """Analyze ingested samples into a :class:`PersonaProfile`."""
    blend = blend or {"social_posts": 0.40, "past_chats": 0.35, "stated_preferences": 0.25}
    social = list(getattr(ingest, "social_posts", []) or [])
    chats = list(getattr(ingest, "chat_messages", []) or [])

    social_m = _Metrics(social) if social else None
    chat_m = _Metrics(chats) if chats else None

    # Normalize source weights over the sources we actually have signal from.
    weights: dict[str, float] = {}
    if social_m:
        weights["social_posts"] = blend.get("social_posts", 0.0)
    if chat_m:
        weights["past_chats"] = blend.get("past_chats", 0.0)
    if not weights:
        weights = {"stated_preferences": 1.0}

    def rate(attr: str) -> float:
        values: dict[str, float] = {}
        if social_m:
            values["social_posts"] = getattr(social_m, attr)
        if chat_m:
            values["past_chats"] = getattr(chat_m, attr)
        return _weighted(values, weights)

    emoji_counters = {
        k: m.emoji_counter
        for k, m in (("social_posts", social_m), ("past_chats", chat_m))
        if m
    }
    token_counters = {
        k: m.token_counter
        for k, m in (("social_posts", social_m), ("past_chats", chat_m))
        if m
    }
    slang_counters = {
        k: m.slang_counter
        for k, m in (("social_posts", social_m), ("past_chats", chat_m))
        if m
    }
    opener_counters = {
        k: m.opener_counter
        for k, m in (("social_posts", social_m), ("past_chats", chat_m))
        if m
    }

    emojis = [e for e, _ in _merge_counter(emoji_counters, weights).most_common(8)]
    vocabulary = [w for w, _ in _merge_counter(token_counters, weights).most_common(12)]
    slang = [s for s, _ in _merge_counter(slang_counters, weights).most_common(10)]
    openers = [o for o, _ in _merge_counter(opener_counters, weights).most_common(5)]

    avg_words = rate("avg_words")
    primary_metrics = social_m or chat_m
    tone = voice.strip() if voice.strip() else "warm and curious"

    sample_messages = (chats[:2] + social[:2])[:4]
    exemplars = _pick_exemplars(chats, social, slang=slang, emojis=emojis)

    profile = PersonaProfile(
        tone=tone,
        summary="",
        humor_style=_humor_from_metrics(primary_metrics, voice),
        cadence=_cadence(avg_words),
        vocabulary=vocabulary,
        slang=slang,
        emojis=emojis,
        go_to_openers=openers,
        emoji_rate=round(rate("emoji_rate"), 3),
        exclamation_rate=round(rate("exclaim_rate"), 3),
        question_rate=round(rate("question_rate"), 3),
        ellipsis_user=rate("ellipsis_rate") > 0.25,
        lowercase_ratio=round(rate("lowercase_ratio"), 3),
        avg_message_words=round(avg_words, 1),
        avg_message_chars=round(rate("avg_chars"), 1),
        sample_messages=sample_messages,
        exemplars=exemplars,
        sources={
            "social_posts": len(social),
            "chat_messages": len(chats),
        },
        blend=blend,
    )

    if not profile.summary:
        profile.summary = (
            f"Texts in a {profile.tone} tone with {profile.humor_style} humor, "
            f"{profile.cadence}."
        )

    profile = _llm_refine(profile, social + chats, router)
    return profile


def build_persona(
    sources: Any,
    *,
    voice: str = "",
    router: Any | None = None,
    save_path: str | Path | None = None,
) -> PersonaProfile:
    """Convenience: ingest configured sources, analyze, and optionally save."""
    from .ingest import ingest_sources

    ingest = ingest_sources(sources)
    blend = None
    blend_obj = getattr(sources, "blend", None)
    if blend_obj is not None and hasattr(blend_obj, "as_dict"):
        blend = blend_obj.as_dict()
    profile = analyze_persona(ingest, voice=voice, blend=blend, router=router)
    if save_path:
        profile.save(save_path)
    return profile


# Structural typing only.
class IngestResultLike:  # pragma: no cover - typing only
    social_posts: list[str]
    chat_messages: list[str]
