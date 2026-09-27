import pytest

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
