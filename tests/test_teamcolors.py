import pytest

from saikaku.teamcolors import MIN_CONTRAST, TEAM_COLORS, colors, contrast, game_colors


@pytest.mark.parametrize("team", list(TEAM_COLORS))
def test_every_team_reads_on_the_background(team):
    assert contrast(colors(team)["main"]) >= MIN_CONTRAST


@pytest.mark.parametrize("other", [t for t in TEAM_COLORS if t != "中日"])
def test_chunichi_and_every_opponent_get_different_readable_colours(other):
    pair = game_colors("中日", other)

    assert pair["中日"]["main"] != pair[other]["main"]
    assert contrast(pair[other]["main"]) >= MIN_CONTRAST


def test_a_same_hue_opponent_is_moved_to_a_lighter_tone():
    pair = game_colors("中日", "DeNA")

    assert contrast(pair["DeNA"]["main"]) < contrast(pair["中日"]["main"]) - 3


def test_unknown_teams_get_a_neutral_colour():
    assert contrast(colors("未知の球団")["main"]) >= MIN_CONTRAST
