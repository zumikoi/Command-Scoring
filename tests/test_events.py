from collections import Counter

import pytest

from saikaku.abilities import AVERAGE, EVENTS, Ability
from saikaku.events import EventTable, measure_fatigue, measure_head_to_head, trip_through_order
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


def _pairs_with(effect: float, seed: int = 1):
    """Synthetic pairs over two seasons, each pair's K rate shifted the same way."""

    import random

    rng = random.Random(seed)
    pairs = {}
    for b in range(30):
        for p in range(30):
            shift = rng.choice((-effect, effect))
            k_rate = 0.22 * (1 + shift)
            for season in ("2023", "2024"):
                n = 15
                k = sum(rng.random() < k_rate for _ in range(n))
                others = {"BB": 1, "1B": 1, "2B": 1, "3B": 1, "HR": 1}
                pairs[(season, f"b{b}", f"p{p}", "same")] = Counter(
                    {"K": k, **others, "OUT": n - k}
                )
    return pairs


def test_head_to_head_measurement_finds_a_planted_effect():
    pseudo, summary = measure_head_to_head(_pairs_with(effect=0.5))

    assert pseudo["K"] < 300
    assert summary["pairs"] == 900
    assert summary["held_out_season"] == "2024"


def test_head_to_head_measurement_finds_nothing_when_there_is_nothing():
    pseudo, _ = measure_head_to_head(_pairs_with(effect=0.0))

    assert pseudo["K"] > 1000


def test_head_to_head_needs_two_seasons():
    one_season = {k: v for k, v in _pairs_with(0.5).items() if k[0] == "2024"}

    pseudo, summary = measure_head_to_head(one_season)

    assert pseudo["K"] == 1_000_000
    assert "note" in summary


def test_forward_uses_head_to_head_for_the_matching_pair(events):
    whiff = {**{e: 1.0 for e in EVENTS}, "K": 50.0}
    lookup = lambda batter, pitcher: whiff if batter is POWER else None

    with_pair = events.forward(2, 0, (POWER,), AVERAGE, lookup)
    without = events.forward(2, 0, (POWER,), AVERAGE)

    assert with_pair[(3, 0, 0)] > without[(3, 0, 0)]



def test_trips_through_the_order():
    assert [trip_through_order(n) for n in (0, 8, 9, 17, 18, 26, 27, 40)] == [1, 1, 2, 2, 3, 3, 3, 3]


def test_fatigue_changes_the_lookahead_only_when_batters_faced_is_known(events):
    from dataclasses import replace

    tired = {**{e: 1.0 for e in EVENTS}, "HR": 2.0}
    table = replace(events, fatigue={"1": {e: 1.0 for e in EVENTS}, "3": tired}, _cache={})

    fresh = table.forward(0, 0, (AVERAGE,), AVERAGE, batters_faced=0)
    third_time = table.forward(0, 0, (AVERAGE,), AVERAGE, batters_faced=20)
    unknown = table.forward(0, 0, (AVERAGE,), AVERAGE)

    def runs(ends):
        return sum(r * p for (_, _, r), p in ends.items())

    assert runs(third_time) > runs(fresh)
    assert runs(unknown) == pytest.approx(runs(fresh))


def test_fatigue_measurement_recovers_a_planted_effect():
    league = {"K": 0.2, "BB": 0.1, "1B": 0.15, "2B": 0.05, "3B": 0.01, "HR": 0.03, "OUT": 0.46}
    season_line = Counter({e: round(r * 1000) for e, r in league.items()})
    batters = {("2024", "b"): season_line}
    pitchers = {("2024", "p"): season_line}
    plays = []
    for trip, hr_share in ((1, 0.02), (3, 0.04)):
        n = 5000
        hrs = int(n * hr_share)
        plays += [("2024", "b", "p", trip, None, "HR")] * hrs
        plays += [("2024", "b", "p", trip, None, "OUT")] * (n - hrs)

    fatigue = measure_fatigue(plays, batters, pitchers, league, {})

    assert fatigue["3"]["HR"] == pytest.approx(2 * fatigue["1"]["HR"], rel=0.01)
