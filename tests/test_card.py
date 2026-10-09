import pytest

from saikaku.card import (
    MAX_HEIGHT,
    POST_LIMIT,
    describe,
    key_decisions,
    long_date,
    post_text,
    weighted_length,
)
from saikaku.game import parse_game, score_game
from tests.test_game import GAME
from tests.test_tactics import SURE_BUNT


@pytest.fixture
def scored(model, events):
    from dataclasses import replace

    from tests.test_game import STRONG

    table = replace(events, batter_profiles=(STRONG,), pitcher_profiles=(), _cache={})
    game = parse_game(GAME, table)
    return game, score_game(game, model, SURE_BUNT, table)


def test_weighted_length_counts_japanese_double():
    assert weighted_length("abc") == 3
    assert weighted_length("采配") == 4
    assert weighted_length("（3-2）") == 7


def test_long_date():
    assert long_date("2026-08-30") == "2026年8月30日（日）"
    assert long_date("サンプル") == "サンプル"


def test_post_text_fits_and_has_the_fixed_lines(scored):
    game, rows = scored

    text = post_text(game, rows)

    assert weighted_length(text) <= POST_LIMIT
    lines = text.splitlines()
    assert lines[0].startswith("【采配採点】9/27")
    assert lines[1].startswith("采配点 ")
    assert lines[-1] == "#采配採点"


def test_key_decisions_are_the_largest_in_game_order(scored):
    _, rows = scored

    keys = key_decisions(rows, limit=2)

    assert all(abs(k.value) >= 0.5 for k in keys)
    assert [k.row.number for k in keys] == sorted(k.row.number for k in keys)


def test_describe_names_who_was_involved(scored):
    _, rows = scored

    assert describe(rows[0]) == "送りバント（乙）"
    assert describe(rows[2]) == "継投（丁→丙）"


def test_cards_fit_one_image_and_split_only_when_needed(scored):
    pytest.importorskip("PIL")
    from saikaku.card import render_cards

    game, rows = scored
    one = render_cards(game, rows)
    many = render_cards(game, [r for r in rows for _ in range(10)])

    assert len(one) == 1 and one[0].size[0] == 1200 and one[0].size[1] <= MAX_HEIGHT
    assert len(many) == 2
