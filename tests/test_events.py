import pytest

from saikaku.abilities import AVERAGE, EVENTS, Ability
from saikaku.events import EventTable
from saikaku.retrosheet import Play
from saikaku.runs import Transition

POWER = Ability({**{e: 1.0 for e in EVENTS}, "HR": 3.0}, "power")


def test_no_batters_leaves_the_state_alone(events):
    assert events.forward(1, 3, ()) == {(1, 3, 0): 1.0}


def test_forward_distributions_are_proper(events):
    ends = events.forward(0, 1, (AVERAGE, POWER, AVERAGE))

    assert sum(ends.values()) == pytest.approx(1.0)
    assert all(0 <= o <= 3 for o, _, _ in ends)


def test_third_out_ends_the_lookahead(events):
    whiffer = Ability({**{e: 1.0 for e in EVENTS}, "K": 1e9}, "whiffer")

    ends = events.forward(2, 0, (whiffer, POWER))

    # The power hitter never comes up once the third out is made.
    assert ends[(3, 0, 0)] == pytest.approx(1.0)


def test_power_raises_expected_runs(events):
    def expected_runs(batter):
        return sum(r * p for (_, _, r), p in events.forward(0, 0, (batter,)).items())

    assert expected_runs(POWER) > expected_runs(AVERAGE)


def test_from_plays_counts_events_by_state():
    plays = [
        Play(Transition(0, 0, 1, 0, 0), plate_appearance=True, event="K", batter="a", pitcher="x", season="2024"),
        Play(Transition(0, 0, 0, 0, 1), plate_appearance=True, event="HR", batter="a", pitcher="x", season="2024"),
        Play(Transition(0, 1, 0, 2, 0), steal_target=2),
    ]

    table = EventTable.from_plays(plays)

    assert table.samples(0, 0) == 2
    assert table.league["HR"] == pytest.approx(0.5)
    assert table.transitions["HR"][(0, 0)] == {(0, 0, 1): 1}


def test_json_round_trip(events):
    restored = EventTable.from_json(events.to_json())

    assert restored.rates == events.rates
    assert restored.transitions == events.transitions
    assert restored.league == pytest.approx(events.league)
