"""MockConnector — a deterministic, offline :class:`MatchSource`.

This lets the entire OpenDate pipeline (and the whole test suite) run with **zero
real credentials and zero network**. The seed data is intentionally chosen to
exercise every interesting situation:

* a fresh match with no messages       -> ``opener`` / ``approaching``
* an active, warming conversation       -> ``flirting`` / ``rapport-building``
* a stalled thread we last messaged      -> ``re-engagement``
* a candidate who hits a dealbreaker     -> ``profile-screening`` pass
* a candidate below the age range        -> ``profile-screening`` pass
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from typing import Any

from .base import Candidate, Match, Message

__all__ = ["MockConnector"]


def _ago(**kwargs: Any) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**kwargs)


def _seed_candidates() -> list[Candidate]:
    return [
        Candidate(
            id="cand-maya",
            name="Maya",
            age=29,
            bio="Weekend boulderer, weekday over-thinker. I will absolutely judge your coffee order (kindly).",
            distance_km=8.0,
            interests=["climbing", "coffee", "live music"],
            jobs=["Product designer"],
            prompts={"My simple pleasures": "negronis, bouldering, and a 9pm walk"},
        ),
        Candidate(
            id="cand-priya",
            name="Priya",
            age=31,
            bio="Cook, concert-goer, recovering spreadsheet addict. Ask me about the best taco in the city.",
            distance_km=15.0,
            interests=["cooking", "live music", "travel"],
            jobs=["Data scientist"],
            prompts={"We'll get along if": "you have strong taco opinions"},
        ),
        Candidate(
            id="cand-sam",
            name="Sam",
            age=27,
            bio="Social smoker, big laugh, bigger playlists. Down for spontaneous road trips.",
            distance_km=12.0,
            interests=["music", "road trips"],
        ),
        Candidate(
            id="cand-alex",
            name="Alex",
            age=33,
            bio="Building a climate startup. Trail runner, amateur baker, will out-plan your weekend.",
            distance_km=22.0,
            interests=["startups", "running", "baking", "climbing"],
            jobs=["Founder"],
        ),
        Candidate(
            id="cand-jordan",
            name="Jordan",
            age=23,
            bio="Just here for the memes and the dog pics.",
            distance_km=5.0,
            interests=["memes", "dogs"],
        ),
    ]


def _seed_matches() -> list[Match]:
    fresh = Match(
        id="match-maya",
        person_id="cand-maya",
        name="Maya",
        bio="Weekend boulderer, weekday over-thinker.",
        created_at=_ago(hours=2),
        last_activity_at=_ago(hours=2),
        messages=[],
    )
    active = Match(
        id="match-priya",
        person_id="cand-priya",
        name="Priya",
        bio="Cook, concert-goer, recovering spreadsheet addict.",
        created_at=_ago(days=2),
        last_activity_at=_ago(minutes=20),
        messages=[
            Message(
                id="m1",
                match_id="match-priya",
                sender="me",
                text="Okay I have to know — what's the best taco in the city and how strongly will we disagree?",
                sent_at=_ago(days=1, hours=3),
            ),
            Message(
                id="m2",
                match_id="match-priya",
                sender="them",
                text="haha bold of you to assume we'll disagree. al pastor, the little place on 5th. fight me 🌮",
                sent_at=_ago(days=1, hours=2),
            ),
            Message(
                id="m3",
                match_id="match-priya",
                sender="me",
                text="That's a genuinely respectable answer. I may have to revoke one (1) of my judgments about you.",
                sent_at=_ago(days=1),
            ),
            Message(
                id="m4",
                match_id="match-priya",
                sender="them",
                text="only one? rude. what would it take to revoke a second 😏",
                sent_at=_ago(minutes=20),
            ),
        ],
    )
    stalled = Match(
        id="match-lena",
        person_id="cand-lena",
        name="Lena",
        bio="Painter, plant hoarder, sunset chaser.",
        created_at=_ago(days=9),
        last_activity_at=_ago(days=4),
        messages=[
            Message(
                id="s1",
                match_id="match-lena",
                sender="them",
                text="that hike photo is unreal, where was that??",
                sent_at=_ago(days=5),
            ),
            Message(
                id="s2",
                match_id="match-lena",
                sender="me",
                text="Right? That's the ridge trail just north of the city — golden hour up there is unfair. You paint, so I feel like you'd love it.",
                sent_at=_ago(days=4),
            ),
        ],
    )
    # Strong rapport, clearly warming toward meeting up -> proposing-a-date.
    warming = Match(
        id="match-noah",
        person_id="cand-noah",
        name="Noah",
        bio="Trail runner, vinyl collector, terrible at chess but won't admit it.",
        created_at=_ago(days=3),
        last_activity_at=_ago(hours=5),
        messages=[
            Message(
                id="n1",
                match_id="match-noah",
                sender="me",
                text="Okay your vinyl shelf is doing a lot of heavy lifting for your whole personality, and I respect it.",
                sent_at=_ago(days=2, hours=6),
            ),
            Message(
                id="n2",
                match_id="match-noah",
                sender="them",
                text="haha it really is my entire identity. what's the last record you actually played start to finish?",
                sent_at=_ago(days=2, hours=5),
            ),
            Message(
                id="n3",
                match_id="match-noah",
                sender="me",
                text="Blue by Joni Mitchell, on a rainy Sunday, fully in my feelings. No regrets.",
                sent_at=_ago(days=2, hours=4),
            ),
            Message(
                id="n4",
                match_id="match-noah",
                sender="them",
                text="okay that's a genuinely elite answer, i might be a little impressed",
                sent_at=_ago(days=1, hours=8),
            ),
            Message(
                id="n5",
                match_id="match-noah",
                sender="me",
                text="I contain multitudes and excellent taste. What's your comfort album when everything's on fire?",
                sent_at=_ago(days=1, hours=7),
            ),
            Message(
                id="n6",
                match_id="match-noah",
                sender="them",
                text="anything by Khruangbin, instant calm. we should genuinely compare record collections in person sometime, i'd love that",
                sent_at=_ago(hours=5),
            ),
        ],
    )
    # Replies have gone flat/low-effort -> recovery is selected, safety backs off.
    fading = Match(
        id="match-rob",
        person_id="cand-rob",
        name="Rob",
        bio="Gym, dog, gym.",
        created_at=_ago(days=4),
        last_activity_at=_ago(hours=2),
        messages=[
            Message(
                id="r1",
                match_id="match-rob",
                sender="me",
                text="Your dog is objectively cuter than you and I think you know it. What's the dog's name?",
                sent_at=_ago(days=1),
            ),
            Message(
                id="r2",
                match_id="match-rob",
                sender="them",
                text="busy",
                sent_at=_ago(hours=6),
            ),
            Message(
                id="r3",
                match_id="match-rob",
                sender="me",
                text="totally, no rush! catch you later",
                sent_at=_ago(hours=5),
            ),
            Message(
                id="r4",
                match_id="match-rob",
                sender="them",
                text="k",
                sent_at=_ago(hours=2),
            ),
        ],
    )
    return [fresh, active, stalled, warming, fading]


class MockConnector:
    """An in-memory, deterministic match source for demos and tests."""

    def __init__(
        self,
        candidates: list[Candidate] | None = None,
        matches: list[Match] | None = None,
    ) -> None:
        self._candidates = candidates if candidates is not None else _seed_candidates()
        self._matches = matches if matches is not None else _seed_matches()
        self._swiped: set[str] = set()
        self.liked: list[str] = []
        self.passed: list[str] = []
        self.sent: list[Message] = []
        self._id_counter = itertools.count(1000)

    async def get_recommendations(self, limit: int = 10) -> list[Candidate]:
        fresh = [c for c in self._candidates if c.id not in self._swiped]
        return fresh[:limit] if limit else fresh

    async def like(self, candidate_id: str) -> dict[str, Any]:
        self._swiped.add(candidate_id)
        self.liked.append(candidate_id)
        candidate = next((c for c in self._candidates if c.id == candidate_id), None)
        if candidate is None:
            return {"match": False}
        # In the mock, a like always becomes a match so downstream flows run.
        match = Match(
            id=f"match-{candidate_id}",
            person_id=candidate.id,
            name=candidate.name,
            bio=candidate.bio,
            created_at=datetime.now(timezone.utc),
            last_activity_at=datetime.now(timezone.utc),
            messages=[],
        )
        if not any(m.id == match.id for m in self._matches):
            self._matches.append(match)
        return {"match": {"_id": match.id, "person": {"_id": candidate.id}}}

    async def pass_(self, candidate_id: str) -> dict[str, Any]:
        self._swiped.add(candidate_id)
        self.passed.append(candidate_id)
        return {"status": 200, "passed": candidate_id}

    async def get_matches(self, count: int = 60) -> list[Match]:
        return self._matches[:count]

    async def get_messages(self, match_id: str, count: int = 100) -> list[Message]:
        match = next((m for m in self._matches if m.id == match_id), None)
        if match is None:
            return []
        return list(match.messages[:count])

    async def send_message(self, match_id: str, text: str) -> Message:
        message = Message(
            id=f"sent-{next(self._id_counter)}",
            match_id=match_id,
            sender="me",
            text=text,
            sent_at=datetime.now(timezone.utc),
        )
        match = next((m for m in self._matches if m.id == match_id), None)
        if match is not None:
            match.messages.append(message)
            match.last_activity_at = message.sent_at
        self.sent.append(message)
        return message

    async def close(self) -> None:  # noqa: D401 - nothing to release
        return None
