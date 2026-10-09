from dataclasses import replace

import pytest

from saikaku.abilities import AVERAGE, EVENTS, Ability
from saikaku.cli import parse_matchup

STRONG = Ability({**{e: 1.0 for e in EVENTS}, "HR": 1.6}, "強打者（上位10%）")
ACE = Ability({**{e: 1.0 for e in EVENTS}, "K": 1.3}, "エース級（上位10%）")


@pytest.fixture
def table(events):
    return replace(events, batter_profiles=(STRONG,), pitcher_profiles=(ACE,), _cache={})


def test_profiles_and_stat_lines_mix(table):
    raw = {
        "打者": "強打者（上位10%）",
        "次の打者": [{"打席": 500, "安打": 100, "本塁打": 2, "四球": 20, "三振": 150}, "リーグ平均"],
        "投手": "エース級（上位10%）",
    }

    matchup = parse_matchup(raw, table)

    assert matchup.lineup[0] is STRONG
    assert matchup.lineup[1].ratio("K") > 1.0
    assert matchup.lineup[2] is AVERAGE
    assert matchup.pitcher is ACE
    assert matchup.pinch_hitter is None


def test_league_line_changes_the_baseline(table):
    batter = {"打席": 600, "安打": 150, "二塁打": 30, "三塁打": 2, "本塁打": 20, "四球": 50, "三振": 120}
    league = {"打席": 60000, "安打": 15000, "二塁打": 3000, "三塁打": 200, "本塁打": 2000,
              "四球": 5000, "三振": 12000}

    against_default = parse_matchup({"打者": batter}, table).lineup[0]
    against_league = parse_matchup({"打者": batter, "リーグ": league}, table).lineup[0]

    assert against_league.ratio("HR") == pytest.approx(1.0, abs=0.01)
    assert against_default.ratio("HR") != pytest.approx(against_league.ratio("HR"))


def test_unknown_profile_is_an_error(table):
    with pytest.raises(KeyError):
        parse_matchup({"打者": "伝説の強打者"}, table)
