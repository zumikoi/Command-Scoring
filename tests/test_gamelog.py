import pytest

from saikaku.abilities import StatLine
from saikaku.gamelog import (
    LogFormatError,
    batters_faced,
    batting_line,
    find_decision,
    parse_log,
    pitching_line,
    steals,
    subtract,
)
from saikaku.game import parse_game, score_game
from tests.test_game import GAME, table  # noqa: F401  (fixture)
from tests.test_tactics import SURE_BUNT


def rows(*lines):
    return [dict(zip(("回", "表裏", "打者", "投手", "結果"), line)) for line in lines]


LOG = parse_log(rows(
    ("1", "表", "甲", "丁", "単打"),
    ("1", "表", "甲", "丁", "盗塁"),
    ("1", "表", "乙", "丁", "三振"),
    ("1", "表", "丙", "丁", "敬遠"),
    ("1", "裏", "子", "丙", "本塁打"),
    ("2", "表", "甲", "丁", "二塁打"),
))


def test_unknown_results_are_rejected():
    with pytest.raises(LogFormatError, match="結果"):
        parse_log(rows(("1", "表", "甲", "丁", "ホームスチール")))


def test_lines_are_counted_from_the_log():
    line = batting_line(LOG, "甲")

    assert (line.pa, line.h, line.doubles, line.so) == (2, 2, 1, 0)
    assert steals(LOG, "甲") == (1, 0)
    pitched = pitching_line(LOG, "丁")
    assert (pitched.pa, pitched.so, pitched.ibb, pitched.bb) == (4, 1, 1, 1)
    assert batters_faced(LOG[:3], "丁") == 2


def test_subtracting_the_game_gives_totals_before_it():
    season = StatLine(pa=100, h=30, doubles=6, triples=1, hr=4, bb=10, hbp=1, so=20)

    before = subtract(season, batting_line(LOG, "甲"), "甲")

    assert (before.pa, before.h, before.doubles) == (98, 28, 5)


def test_subtracting_more_than_the_season_is_an_error():
    with pytest.raises(LogFormatError):
        subtract(StatLine(pa=1, h=0, hr=0, bb=0, hbp=0, so=0), batting_line(LOG, "甲"), "甲")


def test_decisions_are_found_in_order():
    assert find_decision(LOG, 0, 1, "top", "乙") == 2
    assert find_decision(LOG, 3, 1, "top", "甲") is None
    assert find_decision(LOG, 0, 2, "top", "甲") == 5


LOGGED_GAME = GAME.replace("日付: 2026-09-27", "日付: 2026-09-27\n成績の時点: 試合後") + """
## 試合経過

| 回 | 表裏 | 打者 | 投手 | 結果 |
| --- | --- | --- | --- | --- |
| 1 | 表 | 甲 | 丁 | 三振 |
| 3 | 表 | 甲 | 丁 | 三振 |
| 5 | 表 | 甲 | 丁 | 単打 |
| 7 | 表 | 乙 | 丁 | 犠打 |
"""


def test_a_logged_game_subtracts_itself_and_counts_batters_faced(table):
    plain = parse_game(GAME, table)
    logged = parse_game(LOGGED_GAME, table)

    assert logged.decisions[0].log_index == 3
    assert logged.decisions[0].pitcher_faced == 3
    # 乙 had 400 PA after the game, one of them the sacrifice in this game.
    assert logged.players[("乙", True)].ability.ratio("K") != plain.players[("乙", True)].ability.ratio("K")


def test_form_moves_a_struggling_batter_only_slightly(model, table):
    from dataclasses import replace

    pseudo = {e: 50.0 for e in ("K", "BB", "1B", "2B", "3B", "HR")} | {"OUT": 1e6}
    formed = replace(table, form_pseudo={"batter": pseudo, "pitcher": pseudo}, _cache={})
    logged = parse_game(LOGGED_GAME, formed)

    rows_ = score_game(logged, model, SURE_BUNT, formed)

    assert rows_[0].value is not None
