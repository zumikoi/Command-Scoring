"""Tests for the DataStadium loader.

The fixtures below are written by hand against the published 共通仕様書_野球
column list. No licensed data is stored in this repository.
"""

import csv

import pytest

from saikaku.ingest import (
    REQUIRED_COLUMNS,
    SchemaError,
    decision_events,
    parse_runners,
    pitching_changes,
    read_plate_appearances,
)

FLAG_COLUMNS = (
    "is_starter",
    "is_sac_bunt_attempt",
    "is_sh",
    "is_bunt",
    "is_pinch_hitter",
    "is_ibb",
    "is_runner_1b_sb",
    "is_runner_2b_sb",
    "is_runner_1b_cs",
    "is_runner_2b_cs",
    "change_situation",
)


def row(**changes):
    values = {column: "" for column in REQUIRED_COLUMNS + FLAG_COLUMNS}
    values.update(
        game_id="2021029038",
        game_date="2025-03-28",
        inning="7",
        top_bottom_id="1",
        batter_team_id="2",
        batter_team_name="ヤクルト",
        pitcher_team_id="1",
        pitcher_team_name="横浜",
        batter_id="900001",
        batter_name="打者A",
        pitcher_id="800001",
        pitcher_name="投手A",
        pre_out="0",
        pre_runner_situation="100",
        pre_home_team_score="3",
        pre_away_team_score="3",
        post_out="1",
        post_runner_situation="010",
        post_home_team_score="3",
        post_away_team_score="3",
    )
    values.update({column: "0" for column in FLAG_COLUMNS})
    values.update(changes)
    return values


def write_csv(path, rows):
    # The published files carry a UTF-8 byte-order mark; reproduce it so the
    # loader is exercised against the same encoding it will see in production.
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.mark.parametrize(
    "mask,expected",
    [
        ("000", (False, False, False)),
        ("100", (True, False, False)),
        ("010", (False, True, False)),
        ("001", (False, False, True)),
        ("110", (True, True, False)),
        ("101", (True, False, True)),
        ("011", (False, True, True)),
        ("111", (True, True, True)),
    ],
)
def test_parse_runners_follows_the_specification_order(mask, expected):
    assert parse_runners(mask) == expected


@pytest.mark.parametrize("mask", ["", "10", "1000", "abc", "12"])
def test_parse_runners_rejects_malformed_masks(mask):
    with pytest.raises(SchemaError):
        parse_runners(mask)


def test_reads_state_on_both_sides_of_the_event(tmp_path):
    path = write_csv(tmp_path / "atbat.csv", [row()])

    appearance = read_plate_appearances(path)[0]

    assert appearance.before.inning == 7
    assert appearance.before.half == "top"
    assert appearance.before.outs == 0
    assert appearance.before.runners == (True, False, False)
    assert appearance.after.outs == 1
    assert appearance.after.runners == (False, True, False)
    assert appearance.batting_team_name == "ヤクルト"


def test_bottom_of_the_inning_maps_to_the_home_team_batting(tmp_path):
    path = write_csv(tmp_path / "atbat.csv", [row(top_bottom_id="2")])

    appearance = read_plate_appearances(path)[0]

    assert appearance.before.half == "bottom"
    assert appearance.before.batting_team_is_home


def test_third_out_is_loaded_rather_than_rejected(tmp_path):
    path = write_csv(tmp_path / "atbat.csv", [row(post_out="3", post_runner_situation="000")])

    appearance = read_plate_appearances(path)[0]

    assert appearance.after.half_inning_is_over


def test_missing_columns_are_reported_instead_of_guessed(tmp_path):
    incomplete = row()
    del incomplete["pre_runner_situation"]
    path = write_csv(tmp_path / "atbat.csv", [incomplete])

    with pytest.raises(SchemaError, match="pre_runner_situation"):
        read_plate_appearances(path)


def test_pitching_change_is_derived_from_a_new_pitcher_id(tmp_path):
    rows = [
        row(pitcher_id="800001", is_starter="1"),
        row(pitcher_id="800001", is_starter="1"),
        row(pitcher_id="800002"),
    ]
    path = write_csv(tmp_path / "atbat.csv", rows)

    appearances = read_plate_appearances(path)

    assert pitching_changes(appearances) == {2}


def test_the_starters_first_batter_is_not_a_pitching_change(tmp_path):
    path = write_csv(tmp_path / "atbat.csv", [row(is_starter="1")])

    assert pitching_changes(read_plate_appearances(path)) == set()


def test_each_team_tracks_its_own_pitcher(tmp_path):
    rows = [
        row(pitcher_team_id="1", pitcher_id="800001"),
        row(pitcher_team_id="2", pitcher_id="900001"),
        row(pitcher_team_id="1", pitcher_id="800001"),
    ]
    path = write_csv(tmp_path / "atbat.csv", rows)

    # Alternating half innings must not read as repeated pitching changes.
    assert pitching_changes(read_plate_appearances(path)) == set()


def test_change_situation_is_not_treated_as_a_pitching_change(tmp_path):
    path = write_csv(tmp_path / "atbat.csv", [row(change_situation="1")])

    appearance = read_plate_appearances(path)[0]

    assert appearance.situation_changed
    assert list(decision_events([appearance])) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"is_sac_bunt_attempt": "1"},
        {"is_ibb": "1"},
        {"is_pinch_hitter": "1"},
        {"is_runner_1b_sb": "1"},
        {"is_runner_1b_cs": "1"},
    ],
)
def test_manager_choices_are_selected_as_decisions(tmp_path, changes):
    path = write_csv(tmp_path / "atbat.csv", [row(**changes)])

    appearances = read_plate_appearances(path)

    assert len(list(decision_events(appearances))) == 1


def test_a_plain_plate_appearance_is_not_a_decision(tmp_path):
    path = write_csv(tmp_path / "atbat.csv", [row()])

    assert list(decision_events(read_plate_appearances(path))) == []
