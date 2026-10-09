from collections import Counter

import pytest

from saikaku.abilities import (
    AVERAGE,
    BATTER_KEYS,
    EVENTS,
    PITCHER_KEYS,
    Ability,
    StatLine,
    batter_ability,
    league_rates,
    matchup,
    pitcher_ability,
)
from saikaku.events import _profiles

LEAGUE_LINE = StatLine(pa=10000, h=2300, doubles=450, triples=40, hr=300, bb=800, hbp=100, so=2200)
LEAGUE = league_rates(LEAGUE_LINE)


def test_league_rates_sum_to_one():
    assert sum(LEAGUE.values()) == pytest.approx(1.0)
    assert LEAGUE["BB"] == pytest.approx(0.09)


def test_a_league_average_line_has_unit_ratios():
    line = StatLine(pa=1000, h=230, doubles=45, triples=4, hr=30, bb=80, hbp=10, so=220)

    batter = batter_ability(line, LEAGUE)
    pitcher = pitcher_ability(line, LEAGUE)

    for event in EVENTS:
        assert batter.ratio(event) == pytest.approx(1.0, abs=0.01)
        assert pitcher.ratio(event) == pytest.approx(1.0, abs=0.01)


def test_small_samples_are_pulled_toward_the_league():
    hot_start = StatLine(pa=20, h=8, doubles=0, triples=0, hr=5, bb=2, hbp=0, so=3)

    ability = batter_ability(hot_start, LEAGUE)

    raw_ratio = (5 / 20) / LEAGUE["HR"]
    assert 1.0 < ability.ratio("HR") < raw_ratio / 4


def test_pitcher_hits_keep_the_league_mix():
    line = StatLine(pa=700, h=120, hr=10, bb=40, hbp=5, so=220)

    ability = pitcher_ability(line, LEAGUE)

    assert ability.ratio("1B") == pytest.approx(ability.ratio("2B"))
    assert ability.ratio("K") > 1.2


def test_intentional_walks_are_removed():
    with_ibb = StatLine(pa=600, h=150, doubles=30, triples=2, hr=30, bb=90, hbp=5, so=120, ibb=20)

    assert with_ibb.counts()["BB"] == 75
    assert with_ibb.unintentional_pa == 580


def test_stat_lines_read_japanese_keys():
    batter = StatLine.from_mapping(
        {"打席": 500, "安打": 130, "二塁打": 25, "三塁打": 1, "本塁打": 20, "四球": 50, "三振": 100},
        BATTER_KEYS,
    )
    pitcher = StatLine.from_mapping(
        {"打者": 600, "被安打": 130, "被本塁打": 12, "与四球": 40, "奪三振": 150}, PITCHER_KEYS
    )

    assert (batter.pa, batter.doubles, batter.hbp) == (500, 25, 0)
    assert (pitcher.so, pitcher.doubles) == (150, None)


def test_missing_stats_are_named():
    with pytest.raises(ValueError, match="三振"):
        StatLine.from_mapping({"打席": 500, "安打": 130, "本塁打": 20, "四球": 50}, BATTER_KEYS)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(pa=10, h=5, hr=6, bb=0, hbp=0, so=0),
        dict(pa=10, h=5, hr=0, bb=5, hbp=0, so=5),
        dict(pa=10, h=1, hr=0, bb=1, hbp=0, so=1, ibb=2),
        dict(pa=-1, h=0, hr=0, bb=0, hbp=0, so=0),
    ],
)
def test_impossible_lines_are_rejected(kwargs):
    with pytest.raises(ValueError):
        StatLine(**kwargs)


def test_matchup_with_average_players_returns_the_base_rates():
    assert matchup(LEAGUE, AVERAGE, AVERAGE) == pytest.approx(LEAGUE)


def test_matchup_multiplies_both_sides():
    power = Ability({**{e: 1.0 for e in EVENTS}, "HR": 2.0})
    stingy = Ability({**{e: 1.0 for e in EVENTS}, "HR": 0.5})

    assert matchup(LEAGUE, power, stingy)["HR"] == pytest.approx(LEAGUE["HR"])
    assert matchup(LEAGUE, power, AVERAGE)["HR"] > LEAGUE["HR"]
    assert sum(matchup(LEAGUE, power, AVERAGE).values()) == pytest.approx(1.0)


def test_profiles_are_ordered_best_first():
    players = [
        Counter({"K": 120, "BB": 40 + i, "1B": 90, "2B": 25, "3B": 2, "HR": 5 + i, "OUT": 300})
        for i in range(0, 50, 5)
    ]

    batters = _profiles(players, LEAGUE, batting=True)
    pitchers = _profiles(players, LEAGUE, batting=False)

    assert batters[0].ratio("HR") > batters[-1].ratio("HR")
    assert pitchers[0].ratio("HR") < pitchers[-1].ratio("HR")
