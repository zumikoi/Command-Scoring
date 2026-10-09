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


def test_hands_attach_to_profiles_and_lines(table):
    raw = {
        "打者": {"型": "強打者（上位10%）", "左右": "両"},
        "投手": {"打者": 500, "被安打": 110, "被本塁打": 10, "与四球": 30, "奪三振": 120, "左右": "左"},
    }

    matchup = parse_matchup(raw, table)

    assert matchup.lineup[0].hand == "S"
    assert matchup.lineup[0].ratio("HR") == 1.6
    assert matchup.pitcher.hand == "L"


def test_a_pitcher_cannot_be_a_switch_thrower(table):
    with pytest.raises(ValueError, match="左右"):
        parse_matchup({"投手": {"型": "エース級（上位10%）", "左右": "両"}}, table)


def test_head_to_head_records_bind_to_the_named_players(table):
    raw = {
        "打者": "強打者（上位10%）",
        "投手": "エース級（上位10%）",
        "継投": "エース級（上位10%）",
        "対戦成績": {"打者×投手": {"打席": 12, "安打": 1, "本塁打": 0, "四球": 0, "三振": 7}},
    }

    matchup = parse_matchup(raw, table)

    (batter, pitcher, record), = matchup.head_to_head
    assert batter is matchup.lineup[0] and pitcher is matchup.pitcher
    assert record.so == 7


def test_head_to_head_needs_the_players(table):
    with pytest.raises(ValueError, match="代打×投手"):
        parse_matchup({"対戦成績": {"代打×投手": {"打席": 5, "安打": 1, "本塁打": 0, "四球": 0, "三振": 1}}}, table)
