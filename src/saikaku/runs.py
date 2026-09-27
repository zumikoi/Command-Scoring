"""Base-out transitions and the distribution of runs left in a half inning.

A half inning is treated as a Markov chain over the 24 base-out states plus the
absorbing third out. Counting the observed transitions gives the chain, and
solving it gives, for every base-out state, the probability of scoring exactly
``r`` more runs before the third out. The win-probability model builds on that
distribution alone, so the league's run environment enters in one place.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

#: Runs are tracked up to this value; the last bucket holds "this many or more".
DEFAULT_MAX_RUNS = 15

_CONVERGENCE = 1e-12
_MAX_ITERATIONS = 10_000


def base_index(runners: tuple[bool, bool, bool]) -> int:
    """Encode (first, second, third) occupancy as 0-7, first base as the low bit."""

    first, second, third = runners
    return int(first) | int(second) << 1 | int(third) << 2


def state_key(outs: int, bases: int) -> str:
    """Name a base-out state as ``"<outs>-<first><second><third>"``, e.g. ``"1-100"``."""

    return f"{outs}-{bases & 1}{bases >> 1 & 1}{bases >> 2 & 1}"


@dataclass(frozen=True)
class Transition:
    """One play's move between base-out states and the runs it produced."""

    outs_pre: int
    bases_pre: int
    outs_post: int
    bases_post: int
    runs: int

    def __post_init__(self) -> None:
        if self.outs_pre not in {0, 1, 2}:
            raise ValueError(f"outs before a play must be 0-2, got {self.outs_pre}")
        if self.outs_post not in {0, 1, 2, 3} or self.outs_post < self.outs_pre:
            raise ValueError(f"outs after a play must be {self.outs_pre}-3, got {self.outs_post}")
        if not 0 <= self.bases_pre < 8 or not 0 <= self.bases_post < 8:
            raise ValueError("bases must be encoded as 0-7")
        if self.runs < 0:
            raise ValueError("runs must not be negative")


@dataclass
class TransitionTable:
    """Counts of observed transitions, keyed by the starting base-out state."""

    counts: dict[tuple[int, int], Counter[tuple[int, int, int]]] = field(default_factory=dict)

    @classmethod
    def from_transitions(cls, transitions: Iterable[Transition]) -> "TransitionTable":
        table = cls()
        for transition in transitions:
            table.add(transition)
        return table

    def add(self, transition: Transition) -> None:
        outs_post = transition.outs_post
        # Runners left on after the third out do not carry over.
        bases_post = 0 if outs_post == 3 else transition.bases_post
        start = (transition.outs_pre, transition.bases_pre)
        end = (outs_post, bases_post, transition.runs)
        if end == (*start, 0):
            # A record that changes nothing (a failed pickoff, a no-play) is a
            # self-loop. Dropping it leaves the absorption probabilities
            # unchanged and keeps the chain from stalling.
            return
        self.counts.setdefault(start, Counter())[end] += 1

    def total(self) -> int:
        return sum(sum(counter.values()) for counter in self.counts.values())

    def probabilities(self, outs: int, bases: int) -> list[tuple[int, int, int, float]]:
        counter = self.counts.get((outs, bases))
        if not counter:
            raise ValueError(f"no transitions observed from state {state_key(outs, bases)}")
        total = sum(counter.values())
        return [(o, b, r, n / total) for (o, b, r), n in counter.items()]


@dataclass(frozen=True)
class RunDistribution:
    """P(exactly r more runs this half inning) for each base-out state."""

    by_state: dict[tuple[int, int], tuple[float, ...]]
    max_runs: int = DEFAULT_MAX_RUNS
    source: str = ""

    def remaining(self, outs: int, bases: int) -> tuple[float, ...]:
        if outs == 3:
            return (1.0,) + (0.0,) * self.max_runs
        return self.by_state[(outs, bases)]

    def expected_runs(self, outs: int, bases: int) -> float:
        return sum(runs * p for runs, p in enumerate(self.remaining(outs, bases)))

    @classmethod
    def from_table(
        cls, table: TransitionTable, max_runs: int = DEFAULT_MAX_RUNS, source: str = ""
    ) -> "RunDistribution":
        states = [(outs, bases) for outs in range(3) for bases in range(8)]
        moves = {state: table.probabilities(*state) for state in states}
        width = max_runs + 1
        absorbed = [1.0] + [0.0] * max_runs
        current = {state: list(absorbed) for state in states}

        for _ in range(_MAX_ITERATIONS):
            updated: dict[tuple[int, int], list[float]] = {}
            for state in states:
                vector = [0.0] * width
                for outs_post, bases_post, runs, p in moves[state]:
                    tail = absorbed if outs_post == 3 else current[(outs_post, bases_post)]
                    for already, q in enumerate(tail):
                        vector[min(already + runs, max_runs)] += p * q
                updated[state] = vector
            change = max(
                abs(a - b) for state in states for a, b in zip(updated[state], current[state])
            )
            current = updated
            if change < _CONVERGENCE:
                break
        else:
            raise RuntimeError("run distribution did not converge")

        return cls({state: tuple(v) for state, v in current.items()}, max_runs, source)

    def to_json(self) -> str:
        return json.dumps(
            {
                "source": self.source,
                "max_runs": self.max_runs,
                "states": {
                    state_key(outs, bases): list(vector)
                    for (outs, bases), vector in sorted(self.by_state.items())
                },
            },
            ensure_ascii=False,
            indent=1,
        )

    @classmethod
    def from_json(cls, text: str) -> "RunDistribution":
        raw = json.loads(text)
        by_state = {}
        for key, vector in raw["states"].items():
            outs, mask = key.split("-")
            runners = tuple(char == "1" for char in mask)
            by_state[(int(outs), base_index(runners))] = tuple(vector)
        return cls(by_state, raw["max_runs"], raw.get("source", ""))

    @classmethod
    def load(cls, path: str | Path) -> "RunDistribution":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
