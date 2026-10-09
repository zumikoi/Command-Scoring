import pytest

from saikaku.abilities import EVENTS, Ability
from saikaku.game import (
    GameFormatError,
    parse_game,
    parse_runners,
    render_report,
    score_game,
    team_totals,
)
from tests.test_tactics import SURE_BUNT

STRONG = Ability({**{e: 1.0 for e in EVENTS}, "HR": 1.6}, "強打者（上位10%）")


@pytest.fixture
def table(events):
    from dataclasses import replace

    return replace(events, batter_profiles=(STRONG,), pitcher_profiles=(), _cache={})


GAME = """---
日付: 2026-09-27
ビジター: チームA
ホーム: チームB
---

## 選手

| 名前 | 区分 | 左右 | 型 | 打席 | 安打 | 二塁打 | 三塁打 | 本塁打 | 四球 | 死球 | 三振 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 甲 | 打 | 左 | 強打者（上位10%） |  |  |  |  |  |  |  |  |
| 乙 | 打 | 右 |  | 400 | 80 | 10 | 0 | 2 | 20 | 2 | 110 |
| 丙 | 投 | 左 |  | 500 | 100 |  |  | 8 | 30 | 3 | 140 |
| 丁 | 投 | 右 |  |  |  |  |  |  |  |  |  |

## 対戦成績

| 打者 | 投手 | 打席 | 安打 | 二塁打 | 三塁打 | 本塁打 | 四球 | 死球 | 三振 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 乙 | 丙 | 10 | 1 |  |  | 0 | 0 | 0 | 6 |

## 采配

| # | 回 | 表裏 | アウト | 走者 | 得点 | 采配 | 打者 | 次の打者 | その次 | 投手 | 代わり | メモ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 7 | 表 | 0 | 一塁 | 3-3 | 送りバント | 乙 | 甲 |  | 丁 |  | 成功 |
| 2 | 7 | 表 | 0 | 一塁 | 3-3 | 強攻 | 乙 | 甲 |  | 丁 |  |  |
| 3 | 8 | 裏 | 1 | 二塁 | 2-2 | 継投 | 謎の人 |  |  | 丁 | 丙 |  |
| 4 | 8 | 裏 | 1 | 二塁 | 2-2 | 代打 | 乙 |  |  | 丁 |  | 代わりなし |
"""


def test_runners_are_read_in_several_spellings():
    assert parse_runners("なし") == (False, False, False)
    assert parse_runners("一三塁") == (True, False, True)
    assert parse_runners("1,2") == (True, True, False)
    assert parse_runners("満塁") == (True, True, True)
    with pytest.raises(GameFormatError):
        parse_runners("ホーム")


def test_game_note_is_parsed(table):
    game = parse_game(GAME, table)

    assert (game.away, game.home) == ("チームA", "チームB")
    assert game.players[("甲", True)].ability.ratio("HR") == 1.6
    assert game.players[("甲", True)].ability.hand == "L"
    assert game.players[("乙", True)].ability.ratio("K") > 1.0
    assert ("乙", "丙") in game.head_to_head
    assert [d.call for d in game.decisions] == ["送りバント", "強攻", "継投", "代打"]
    assert game.decisions[0].state.away_score == 3
    assert any("謎の人" in w for w in game.warnings)


def test_a_pitcher_who_bats_has_separate_rows(model, table):
    text = GAME.replace(
        "| 丁 | 投 | 右 |  |  |  |  |  |  |  |  |  |",
        "| 丁 | 投 | 右 |  | 500 | 90 |  |  | 5 | 20 | 2 | 200 |\n"
        "| 丁 | 打 | 右 |  | 100 | 5 | 0 | 0 | 0 | 2 | 0 | 50 |",
    )

    game = parse_game(text, table)

    assert game.players[("丁", False)].ability.ratio("K") > 1.3
    assert game.players[("丁", True)].ability.ratio("K") > 1.5
    assert game.players[("丁", False)].ability is not game.players[("丁", True)].ability


def test_a_declined_call_scores_the_opposite_of_the_call(model, table):
    game = parse_game(GAME, table)

    rows = score_game(game, model, SURE_BUNT, table)

    bunt, no_bunt = rows[0], rows[1]
    assert no_bunt.value == pytest.approx(-bunt.value)
    assert no_bunt.chosen_label == "強攻"
    assert bunt.team == no_bunt.team == "チームA"


def test_defensive_calls_belong_to_the_fielding_team(model, table):
    rows = score_game(parse_game(GAME, table), model, SURE_BUNT, table)

    assert rows[2].team == "チームA"  # bottom of the 8th: A is in the field
    assert rows[2].value is not None


def test_substitutions_without_a_substitute_are_reported_not_scored(model, table):
    rows = score_game(parse_game(GAME, table), model, SURE_BUNT, table)

    assert rows[3].value is None
    assert "代わり" in rows[3].problem


def test_team_totals_and_report(model, table):
    game = parse_game(GAME, table)
    rows = score_game(game, model, SURE_BUNT, table)

    totals = {t.team: t for t in team_totals(game, rows)}
    report = render_report(game, rows, "2026-09-27_A-B")

    assert totals["チームA"].total == pytest.approx(sum(r.value for r in rows if r.value is not None))
    assert totals["チームB"].scored == []
    assert "[[2026-09-27_A-B]]" in report
    assert "対象外" in report


@pytest.mark.parametrize(
    "broken, message",
    [
        ("| 1 | 7 | 中 | 0 | 一塁 | 3-3 | 送りバント | 乙 |  |  | 丁 |  |  |", "表裏"),
        ("| 1 | 7 | 表 | 0 | 一塁 | 3対3 | 送りバント | 乙 |  |  | 丁 |  |  |", "得点"),
        ("| 1 | 7 | 表 | 0 | 一塁 | 3-3 | スクイズ | 乙 |  |  | 丁 |  |  |", "采配"),
        ("| 1 | 7 | 表 | 4 | 一塁 | 3-3 | 送りバント | 乙 |  |  | 丁 |  |  |", "outs"),
    ],
)
def test_bad_rows_say_what_is_wrong(table, broken, message):
    text = GAME.replace("| 1 | 7 | 表 | 0 | 一塁 | 3-3 | 送りバント | 乙 | 甲 |  | 丁 |  | 成功 |", broken)

    with pytest.raises(GameFormatError, match=message):
        parse_game(text, table)
