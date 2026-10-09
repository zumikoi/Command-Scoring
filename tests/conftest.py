from collections import Counter

import pytest

from saikaku.events import EventTable
from saikaku.model import WinProbabilityModel
from saikaku.runs import RunDistribution, Transition, TransitionTable


def toy_table() -> TransitionTable:
    """A small but complete chain: outs, singles that push runners, home runs."""

    table = TransitionTable()
    for outs in range(3):
        for bases in range(8):
            for _ in range(7):
                table.add(Transition(outs, bases, outs + 1, bases, 0))
            # Single: every runner moves up one base, the runner on third scores.
            pushed = ((bases << 1) | 1) & 0b111
            scored = bases >> 2 & 1
            for _ in range(2):
                table.add(Transition(outs, bases, outs, pushed, scored))
            table.add(Transition(outs, bases, outs, 0, bin(bases).count("1") + 1))
    return table


@pytest.fixture(scope="session")
def runs() -> RunDistribution:
    return RunDistribution.from_table(toy_table())


@pytest.fixture(scope="session")
def model(runs) -> WinProbabilityModel:
    return WinProbabilityModel(runs)


TOY_RATES = {"K": 22, "BB": 9, "1B": 14, "2B": 5, "3B": 1, "HR": 3, "OUT": 46}


def _advance(bases: int, push: int) -> tuple[int, int]:
    """Move every runner and the batter ``push`` bases; return (bases, runs)."""

    runners = [i + 1 for i in range(3) if bases >> i & 1] + [0]
    moved = [r + push for r in runners]
    runs = sum(1 for r in moved if r >= 4)
    new = sum(1 << (r - 1) for r in moved if r < 4)
    return new, runs


def _walk(bases: int) -> tuple[int, int]:
    first, second, third = bases & 1, bases >> 1 & 1, bases >> 2 & 1
    runs = 0
    if first:
        if second:
            runs = third
            third = 1
        second = 1
    return 1 | second << 1 | third << 2, runs


def toy_events() -> EventTable:
    rates, transitions = {}, {e: {} for e in TOY_RATES}
    for outs in range(3):
        for bases in range(8):
            state = (outs, bases)
            rates[state] = Counter(TOY_RATES)
            transitions["K"][state] = Counter({(outs + 1, 0 if outs == 2 else bases, 0): 1})
            transitions["OUT"][state] = Counter({(outs + 1, 0 if outs == 2 else bases, 0): 1})
            transitions["BB"][state] = Counter({(outs, *_walk(bases)): 1})
            for event, push in (("1B", 1), ("2B", 2), ("3B", 3), ("HR", 4)):
                transitions[event][state] = Counter({(outs, *_advance(bases, push)): 1})
    total = sum(TOY_RATES.values())
    return EventTable(rates, transitions, {e: n / total for e, n in TOY_RATES.items()})


@pytest.fixture(scope="session")
def events() -> EventTable:
    return toy_events()
