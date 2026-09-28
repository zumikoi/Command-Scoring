"""What each tactic tends to produce, and what a decision was worth.

A decision is judged before its result is known: the chosen tactic and its
alternative are each turned into a distribution of next base-out states, and
their expected win probabilities are compared. The actual result plays no part.

Swinging away, bunting and stealing are estimated from play-by-play data. An
intentional walk needs no data, since the batter always takes first and only
forced runners move. Leaving the runner put is the current state itself.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

from .model import GameState, WinProbabilityModel
from .retrosheet import Play
from .runs import base_index, state_key

DEFAULT_TACTICS = Path(__file__).with_name("data") / "tactics.json"

#: Fewer observations than this and an estimate is reported as unavailable.
MIN_SAMPLES = 50

TACTIC_NAMES = {
    "swing": "通常打撃",
    "bunt": "送りバント",
    "steal2": "二盗",
    "steal3": "三盗",
    "stay": "自重",
    "ibb": "敬遠",
}

#: Tactics whose outcomes come from data rather than from the rules.
ESTIMATED = ("swing", "bunt", "steal2", "steal3")


@dataclass(frozen=True)
class DecisionType:
    chosen: str
    alternative: str
    #: The side that made the call; its perspective sets the sign of the score.
    by_offense: bool
    #: Whether the call makes sense from a base-out state at all.
    applies: Callable[[int, int], bool]


DECISION_TYPES = {
    "送りバント": DecisionType("bunt", "swing", True, lambda outs, bases: outs < 2 and bases != 0),
    "二盗": DecisionType("steal2", "stay", True, lambda outs, bases: bases & 0b011 == 0b001),
    "三盗": DecisionType("steal3", "stay", True, lambda outs, bases: bases & 0b110 == 0b010),
    "敬遠": DecisionType("ibb", "swing", False, lambda outs, bases: True),
}

UNSUPPORTED = {
    "継投": "投手ごとの能力を推定できるデータがないため評価しない",
    "代打": "打者ごとの能力を推定できるデータがないため評価しない",
}


class InsufficientData(LookupError):
    """Raised when a tactic was seldom tried from a state to estimate it."""


Outcome = tuple[int, int, int, float]  # outs, bases, runs, probability


@dataclass(frozen=True)
class TacticTable:
    """Observed outcome counts per tactic and base-out state."""

    counts: dict[str, dict[tuple[int, int], Counter[tuple[int, int, int]]]]
    source: str = ""

    @classmethod
    def from_plays(cls, plays: Iterable[Play], source: str = "") -> "TacticTable":
        counts: dict[str, dict[tuple[int, int], Counter]] = {name: {} for name in ESTIMATED}
        for play in plays:
            tactic = classify(play)
            if tactic is None:
                continue
            t = play.transition
            bases_post = 0 if t.outs_post == 3 else t.bases_post
            counts[tactic].setdefault((t.outs_pre, t.bases_pre), Counter())[
                (t.outs_post, bases_post, t.runs)
            ] += 1
        return cls(counts, source)

    def samples(self, tactic: str, outs: int, bases: int) -> int:
        if tactic in ("stay", "ibb"):
            return 0
        return sum(self.counts[tactic].get((outs, bases), Counter()).values())

    def outcomes(self, tactic: str, outs: int, bases: int) -> list[Outcome]:
        if tactic == "stay":
            return [(outs, bases, 0, 1.0)]
        if tactic == "ibb":
            return [intentional_walk(outs, bases)]
        counter = self.counts[tactic].get((outs, bases), Counter())
        total = sum(counter.values())
        if total < MIN_SAMPLES:
            raise InsufficientData(
                f"{TACTIC_NAMES[tactic]} from {state_key(outs, bases)}: {total} samples"
            )
        return sorted(
            ((o, b, r, n / total) for (o, b, r), n in counter.items()),
            key=lambda outcome: -outcome[3],
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "source": self.source,
                "tactics": {
                    tactic: {
                        state_key(*state): [[o, b, r, n] for (o, b, r), n in sorted(c.items())]
                        for state, c in sorted(by_state.items())
                    }
                    for tactic, by_state in self.counts.items()
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, text: str) -> "TacticTable":
        raw = json.loads(text)
        counts = {}
        for tactic, by_state in raw["tactics"].items():
            counts[tactic] = {}
            for key, rows in by_state.items():
                outs, mask = key.split("-")
                state = (int(outs), base_index(tuple(char == "1" for char in mask)))
                counts[tactic][state] = Counter({(o, b, r): n for o, b, r, n in rows})
        return cls(counts, raw.get("source", ""))

    @classmethod
    def load(cls, path: str | Path = DEFAULT_TACTICS) -> "TacticTable":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


def classify(play: Play) -> str | None:
    """Name the tactic a play represents, or None if it isolates no choice."""

    if play.steal_target == 2:
        return "steal2"
    if play.steal_target == 3:
        return "steal3"
    if not play.plate_appearance or play.intentional_walk:
        return None
    return "bunt" if play.bunt_attempt else "swing"


def intentional_walk(outs: int, bases: int) -> Outcome:
    """The batter takes first; each runner moves only if forced."""

    first, second, third = bases & 1, bases >> 1 & 1, bases >> 2 & 1
    runs = 0
    if first:
        if second:
            if third:
                runs = 1
            third = 1
        second = 1
    return (outs, 1 | second << 1 | third << 2, runs, 1.0)


def after(state: GameState, outs: int, bases: int, runs: int) -> GameState:
    runners = (bool(bases & 1), bool(bases & 2), bool(bases & 4))
    moved = replace(state, outs=outs, runners=runners)
    if state.batting_team_is_home:
        return replace(moved, home_score=state.home_score + runs)
    return replace(moved, away_score=state.away_score + runs)


def expected_probability(
    model: WinProbabilityModel, state: GameState, outcomes: list[Outcome]
) -> float:
    """The batting team's win probability averaged over a tactic's outcomes."""

    return sum(p * model.probability(after(state, o, b, r)) for o, b, r, p in outcomes)


@dataclass(frozen=True)
class Evaluation:
    decision_type: str
    chosen: str
    alternative: str
    #: Win probabilities from the deciding team's side, 0-1.
    chosen_probability: float
    alternative_probability: float
    chosen_samples: int
    alternative_samples: int

    @property
    def value(self) -> float:
        """Chosen minus alternative, in percentage points."""

        return (self.chosen_probability - self.alternative_probability) * 100


def evaluate(
    decision_type: str,
    state: GameState,
    model: WinProbabilityModel,
    table: TacticTable,
) -> Evaluation:
    if decision_type in UNSUPPORTED:
        raise InsufficientData(f"{decision_type}: {UNSUPPORTED[decision_type]}")
    kind = DECISION_TYPES[decision_type]
    bases = base_index(state.runners)
    if state.outs > 2 or not kind.applies(state.outs, bases):
        raise ValueError(f"{decision_type} is not possible from {state_key(state.outs, bases)}")

    def side(probability: float) -> float:
        return probability if kind.by_offense else 1.0 - probability

    values = {
        tactic: side(expected_probability(model, state, table.outcomes(tactic, state.outs, bases)))
        for tactic in (kind.chosen, kind.alternative)
    }
    return Evaluation(
        decision_type=decision_type,
        chosen=kind.chosen,
        alternative=kind.alternative,
        chosen_probability=values[kind.chosen],
        alternative_probability=values[kind.alternative],
        chosen_samples=table.samples(kind.chosen, state.outs, bases),
        alternative_samples=table.samples(kind.alternative, state.outs, bases),
    )
