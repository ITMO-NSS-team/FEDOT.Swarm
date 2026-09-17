from __future__ import annotations

import random
import re
from collections.abc import Callable, Iterable
from typing import Any

from fedotmas import Board, Rule, blackboard
from fedotmas.engine import ActivitySample, View
from fedotmas.engine.contract import Fact
from fedotmas_llm import PromptRule

# pydantic refuses typing.TypedDict as a schema source below 3.12
from typing_extensions import TypedDict

from fedotmas_meta._assemble import Agent, Fill
from fedotmas_meta._spec import RoleSpec, SpecError

CONDUCT = (
    "You post on a public feed. Write ONE post of at most two sentences, in character, "
    "answering the topic and reacting to the feed if it is not empty. No preamble, no "
    "quotes, no hashtags."
)
FEED = "Topic: {topic}\nRound: {input}\nFeed so far:\n{feed}"
SEAT = "You are: {cast[hired][NAME]}\n" + FEED
EMPTY = "(nothing yet)"

QUEEN = """You run the casting for a public feed arguing one topic. Each round you may seat a
new voice in a free seat, or send one home, or do nothing.

Answer with {{"hire": {{"<a free seat>": "<the character>"}}, "retire": ["<a name>"]}}. The
value under a seat is the character itself, written in the second person the way the others
were written, one or two sentences: "You are a ... who ...". It is never a name.

Seat a voice when the feed keeps circling and nobody present can break it. Send one home when
it has stopped saying anything the others do not already say. Most rounds the right answer is
neither, and {{"hire": {{}}, "retire": []}} is a real answer.

The voices already in the room are: {room}.
The free seats are: {seats}. Never seat anyone anywhere else, and only ever send home a name
from one of those two lists."""

CASTING = "Round: {input}\nChanges so far: {cast}\nFeed so far:\n{feed}"


class Amendment(TypedDict):
    """What the queen may change this round: characters to seat, keyed by a free seat, and
    names to send home. Both empty is the usual answer. A TypedDict and not a model because a
    fact has to survive SqliteStore, which keeps values as json."""

    hire: dict[str, str]
    retire: list[str]


class Cast(TypedDict):
    """Who is in the room, folded from the queen's amendments: the occupied seats and everyone
    sent home. A seat reads its own character out of `hired`, a persona checks `retired`."""

    hired: dict[str, str]
    retired: list[str]


Ranker = Callable[[Agent, list[Fact]], list[Fact]]


def by_interest(agent: Agent, posts: list[Fact]) -> list[Fact]:
    """Stand-in for the recommender OASIS puts between the platform and an agent: order posts
    by how much of their vocabulary the persona already uses, recent first among equals. Word
    overlap rather than embeddings, so it stays free and offline."""
    words = _words(agent.prompt)
    scored = [(len(words & _words(str(f.value))), i, f) for i, f in enumerate(posts)]
    return [f for _, _, f in sorted(scored, key=lambda s: s[:2], reverse=True)]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", text.lower()))


class SwarmPreset:
    """Many personas posting to one shared feed over a run of rounds: the clock re-arms every
    persona each round, ActivitySample decides which of them actually speak, and a feed rule
    folds the posts so far into what they read next. A spec fills the voices; cadence and feed
    width are the preset's own, so a composed swarm stays comparable to a handwritten one.

    With `ranker` set, each persona gets its own feed rule and reads its own ranking of the
    same posts, which is what lets a room split rather than converge. Seed a run with
    `seed(topic)` and let it end on its round budget: nothing writes a goal.
    """

    name = "swarm"
    hint = "many personas argue a topic on one shared feed, a few speaking each round"
    roles = (
        RoleSpec(
            "personas", "one per voice you want in the room, keyed by a short id", True
        ),
    )

    def __init__(
        self,
        *,
        feed_width: int = 12,
        min_active: int = 3,
        max_active: int | None = 8,
        activity: tuple[float, float] = (0.2, 1.0),
        ranker: Ranker | None = None,
        casting: bool = False,
        seats: int = 4,
        rng: random.Random | None = None,
        conduct: str = CONDUCT,
    ) -> None:
        self.feed_width = feed_width
        self.min_active = min_active
        self.max_active = max_active
        self.activity = activity
        self.ranker = ranker
        self.casting = casting
        self.seats = seats if casting else 0
        self._rng = rng or random.Random()
        self.conduct = conduct

    @property
    def reserved(self) -> frozenset[str]:
        """Grows with casting: the queen, the fold and every free seat are nodes too, so a
        composed persona must not be named after one."""
        names = {"clock", "feed"}
        if self.casting:
            names |= {"queen", "cast", *self._seats()}
        return frozenset(names)

    def _seats(self) -> list[str]:
        return [f"seat_{i}" for i in range(self.seats)]

    def seed(self, topic: str, personas: Iterable[str] = ()) -> dict[str, Any]:
        """The opening facts. With a ranker every persona reads its own feed tag, and a tag
        nothing has written yet is a missing template reference, so the cast has to be named
        here for the first round to run at all."""
        feeds = [f"feed_{n}" for n in personas] if self.ranker is not None else []
        if self.ranker is None or self.casting:
            feeds.append("feed")
        opening: dict[str, Any] = {"tick": 0, "topic": topic}
        if self.casting:
            opening["cast"] = Cast(hired={}, retired=[])
        return opening | {tag: EMPTY for tag in feeds}

    def build(self, fill: Fill) -> Board:
        personas = fill["personas"]
        assert isinstance(personas, dict)
        agents = list(personas.values())
        feeds = self._ranked(agents) if self.ranker is not None else []
        # a seat reads the common wall even when the personas read their own rankings: what
        # it is interested in is not known until the cast seats someone in it
        if self.ranker is None or self.casting:
            feeds.append(self._feed())
        casting = (
            [
                self._queen([a.name for a in agents]),
                self._fold(),
                *(self._seat(s) for s in self._seats()),
            ]
            if self.casting
            else []
        )
        return blackboard(
            self._clock(),
            *feeds,
            *casting,
            *(self._persona(a) for a in agents),
            policy=ActivitySample(self.min_active, self.max_active, rng=self._rng),
            halt_on_error=False,
        )

    def _queen(self, room: list[str]) -> PromptRule:
        """The casting agent, a rule on the board it is casting: it reads the feed its own
        personas wrote and answers with an amendment. Nothing about it is privileged, it just
        writes a fact the others happen to read."""
        return PromptRule(
            name="queen",
            prompt=QUEEN.format(room=room, seats=self._seats()),
            input=CASTING,
            returns=Amendment,
            reads="tick",
            writes="amendment",
            when=lambda v: True,
        )

    def _fold(self) -> Rule:
        """Folds amendments into the standing cast. Code and not a prompt on purpose: asking a
        model to restate the whole room every round is how a room loses members. An occupied
        seat keeps its occupant, so a queen that forgets which seats it has used cannot rewrite
        a persona out from under the posts it has already made."""

        async def fold(amendment: Amendment, view: View) -> Cast:
            cast = _cast_of(view)
            retired = list(
                dict.fromkeys([*cast["retired"], *amendment.get("retire", ())])
            )
            hired = dict(cast["hired"])
            for seat, character in amendment.get("hire", {}).items():
                hired.setdefault(seat, character)
            return Cast(
                hired={k: v for k, v in hired.items() if k not in retired},
                retired=retired,
            )

        return Rule(
            name="cast",
            fn=fold,
            reads="amendment",
            writes="cast",
            when=lambda v: v.exists("amendment"),
        )

    def _seat(self, name: str) -> PromptRule:
        """A free seat: a persona whose character is a fact instead of a string fixed at
        compile, so it exists only while the cast seats someone in it and is whoever that is.
        This is the whole trick of a live roster, and it needs nothing from the engine."""
        return PromptRule(
            name=name,
            prompt=self.conduct,
            input=SEAT.replace("NAME", name),
            reads="tick",
            writes="post",
            when=lambda v, n=name: n in _cast_of(v)["hired"],
            meta={"activity_level": self._rng.uniform(*self.activity)},
        )

    def _clock(self) -> Rule:
        """Rewrites `tick` every round, which is what re-arms the personas: the executor fires
        a node once per distinct matched input, so a fresh tick is a fresh input for all."""

        async def tick(v: int) -> int:
            return v + 1

        return Rule(
            name="clock", fn=tick, reads="tick", writes="tick", when=lambda v: True
        )

    def _feed(self, agent: Agent | None = None) -> Rule:
        """Infrastructure, so it carries no activity_level and always fires. Writes land at
        the end of a superstep, so the feed a persona reads trails the store by one round."""
        width, ranker = self.feed_width, self.ranker
        tag = _feed_tag(agent)

        async def digest(_: int, view: View) -> str:
            posts = view.query("post")
            if ranker is not None and agent is not None:
                keep = {f.key for f in ranker(agent, posts)[:width]}
                posts = [f for f in posts if f.key in keep]
            return (
                "\n".join(f"{f.producer}: {f.value}" for f in posts[-width:]) or EMPTY
            )

        return Rule(name=tag, fn=digest, reads="tick", writes=tag, when=lambda v: True)

    def _ranked(self, agents: list[Agent]) -> list[Rule]:
        taken = {a.name for a in agents} & {_feed_tag(a) for a in agents}
        if taken:
            raise SpecError(f"personas {sorted(taken)} shadow their own feed rules")
        return [self._feed(a) for a in agents]

    def _persona(self, agent: Agent) -> PromptRule:
        """The spec supplies the character, the preset the conduct: what this medium rewards
        is the preset's business, not the meta-agent's."""
        template = FEED
        if self.ranker is not None:
            template = FEED.replace("{feed}", f"{{{_feed_tag(agent)}}}")
        alive: Callable[[View], bool] = lambda v: True
        if self.casting:
            alive = lambda v, n=agent.name: n not in _cast_of(v)["retired"]
        return PromptRule(
            name=agent.name,
            prompt=f"{agent.prompt}\n{self.conduct}",
            input=template,
            reads="tick",
            writes="post",
            when=alive,
            llm=agent.llm,
            tools=list(agent.tools) or None,
            meta={"activity_level": self._rng.uniform(*self.activity)},
        )


def _feed_tag(agent: Agent | None) -> str:
    return "feed" if agent is None else f"feed_{agent.name}"


def _cast_of(view: View) -> Cast:
    cast = view.value("cast")
    if not isinstance(cast, dict):
        return Cast(hired={}, retired=[])
    return Cast(hired=cast.get("hired", {}), retired=cast.get("retired", []))
