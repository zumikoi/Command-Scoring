import pytest

from saikaku.gamelog import LogFormatError, parse_log
from saikaku.winprob import focus, player_totals, report_section, series, swings


def rows(*lines):
    keys = ("回", "表裏", "打者", "投手", "結果", "アウト", "走者", "得点")
    return [dict(zip(keys, line)) for line in lines]


LOG = parse_log(rows(
    ("1", "表", "甲", "丁", "本塁打", "0", "なし", "1-0"),
    ("1", "表", "乙", "丁", "三振", "1", "なし", "1-0"),
    ("1", "表", "丙", "丁", "単打", "1", "一塁", "1-0"),
    ("1", "表", "丙", "丁", "盗塁", "1", "二塁", "1-0"),
    ("1", "表", "戊", "丁", "併殺", "3", "なし", "1-0"),
    ("1", "裏", "子", "甲投", "三振", "1", "なし", "1-0"),
))


def test_focus_prefers_chunichi_then_home():
    assert focus("中日", "ヤクルト") == ("中日", False)
    assert focus("巨人", "阪神") == ("阪神", True)
    assert focus("巨人", "阪神", "巨人") == ("巨人", False)


def test_every_play_moves_the_line_and_the_last_one_settles_it(model):
    points = series(LOG, model, focus_is_home=False)

    assert len(points) == len(LOG) + 1
    assert points[1].delta > 0          # the visitors' home run
    assert points[2].delta < 0          # a strikeout
    assert points[4].delta > 0          # a stolen base, between plate appearances
    assert points[-1].wp == 1.0         # the last row ends it, visitors ahead
    assert sum(p.delta for p in points) == pytest.approx(points[-1].wp - points[0].wp)


def test_series_needs_the_situation_on_every_row(model):
    bare = parse_log([{"回": "1", "表裏": "表", "打者": "甲", "投手": "丁", "結果": "三振"}])

    assert series(bare, model, focus_is_home=True) is None


def test_bad_situations_are_reported():
    with pytest.raises(LogFormatError, match="アウト"):
        parse_log(rows(("1", "表", "甲", "丁", "三振", "1", "なし", "1対0")))


def test_swings_and_credit(model):
    points = series(LOG, model, focus_is_home=False)

    top = swings(points, count=2)
    totals = player_totals(points, focus_is_home=False)

    assert [p.x for p in top] == sorted(p.x for p in top)
    assert totals[("甲", "打")] > 0
    assert totals[("丁", "投")] < 0
    assert totals[("丙", "打")] > 0      # the single and the steal


def test_report_section_lists_the_swings(model):
    points = series(LOG, model, focus_is_home=False)

    text = "\n".join(report_section(points, "ビジター", False, "x.png"))

    assert "![[x.png]]" in text
    assert "甲 本塁打" in text
