import pytest

from saikaku.teamcolors import MIN_CONTRAST, TEAM_COLORS, complement, contrast, palette


@pytest.mark.parametrize("team", list(TEAM_COLORS))
def test_every_team_reads_on_the_background(team):
    colors = palette(team)

    assert contrast(colors["pos"]) >= MIN_CONTRAST
    assert contrast(colors["neg"]) >= MIN_CONTRAST
    assert colors["pos"] != colors["neg"]


def test_chunichi_and_dena_do_not_share_colours():
    chunichi, dena = palette("中日"), palette("DeNA")

    assert {chunichi["pos"], chunichi["neg"]}.isdisjoint({dena["pos"], dena["neg"]})


def test_complement_turns_blue_toward_orange():
    r, g, b = (int(complement("#0091D7")[i:i + 2], 16) for i in (1, 3, 5))

    assert r > b


def test_unknown_teams_fall_back_to_green_and_red():
    assert palette("未知の球団")["pos"] == "#1B7A55"
