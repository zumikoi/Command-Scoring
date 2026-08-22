"""Load DataStadium NPB event data into the project's game-state model.

The column layout follows the "共通仕様書_野球" specification published as a
sample on the さっぽろ圏データ取引市場 open-data portal. Only the columns this
project actually needs are read; the file carries 208 in total.

No data ships with this repository. Point the loader at files obtained under a
DataStadium licence. See DATA_SOURCES.md for the licence status.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .model import GameState

#: DataStadium encodes the bases as a three-character mask, first base first.
RUNNER_MASK_LENGTH = 3

#: ``top_bottom_id`` uses 1 for the top of an inning and 2 for the bottom.
_HALVES = {"1": "top", "2": "bottom"}

#: Columns the loader requires. Missing any of these is a hard error, because a
#: silently absent column would produce plausible but wrong game states.
REQUIRED_COLUMNS = (
    "game_id",
    "game_date",
    "inning",
    "top_bottom_id",
    "batter_team_id",
    "batter_team_name",
    "pitcher_team_id",
    "pitcher_team_name",
    "batter_id",
    "batter_name",
    "pitcher_id",
    "pitcher_name",
    "pre_out",
    "pre_runner_situation",
    "pre_home_team_score",
    "pre_away_team_score",
    "post_out",
    "post_runner_situation",
    "post_home_team_score",
    "post_away_team_score",
)


class SchemaError(ValueError):
    """Raised when an input file does not match the expected specification."""


@dataclass(frozen=True)
class PlateAppearance:
    """One row of DataStadium's 打席イベントデータ.

    ``before`` and ``after`` are the game states bracketing the event, which is
    exactly the pair the scoring model compares.
    """

    game_id: str
    game_date: str
    batting_team_id: str
    batting_team_name: str
    fielding_team_id: str
    fielding_team_name: str
    batter_id: str
    batter_name: str
    pitcher_id: str
    pitcher_name: str
    before: GameState
    after: GameState
    is_starter: bool
    is_sac_bunt_attempt: bool
    is_sacrifice_hit: bool
    is_bunt: bool
    is_pinch_hitter: bool
    is_intentional_walk: bool
    stolen_base: bool
    caught_stealing: bool
    #: ``change_situation`` marks that the batter, out count or runners moved
    #: between the pre and post columns. It is not a pitching change.
    situation_changed: bool


def parse_runners(mask: str) -> tuple[bool, bool, bool]:
    """Convert a ``pre_runner_situation`` mask such as ``"101"`` to base flags.

    The specification lists 000 (走者なし), 100 (一塁), 110 (一二塁),
    101 (一三塁), 010 (二塁), 011 (二三塁), 001 (三塁) and 111 (満塁), so the
    characters map to first, second and third base in order.
    """

    text = mask.strip()
    if len(text) != RUNNER_MASK_LENGTH or any(char not in "01" for char in text):
        raise SchemaError(f"runner situation must be three 0/1 characters, got {mask!r}")
    first, second, third = (char == "1" for char in text)
    return (first, second, third)


def _flag(row: dict[str, str], column: str) -> bool:
    """Read a DataStadium smallint flag column, treating a blank as false."""

    value = row.get(column, "").strip()
    return value not in {"", "0"}


def _state(row: dict[str, str], prefix: str) -> GameState:
    half = _HALVES.get(row["top_bottom_id"].strip())
    if half is None:
        raise SchemaError(f"top_bottom_id must be 1 or 2, got {row['top_bottom_id']!r}")
    return GameState(
        inning=int(row["inning"]),
        half=half,
        outs=int(row[f"{prefix}_out"]),
        home_score=int(row[f"{prefix}_home_team_score"]),
        away_score=int(row[f"{prefix}_away_team_score"]),
        runners=parse_runners(row[f"{prefix}_runner_situation"]),
    )


def _to_plate_appearance(row: dict[str, str]) -> PlateAppearance:
    return PlateAppearance(
        game_id=row["game_id"].strip(),
        game_date=row["game_date"].strip(),
        batting_team_id=row["batter_team_id"].strip(),
        batting_team_name=row["batter_team_name"].strip(),
        fielding_team_id=row["pitcher_team_id"].strip(),
        fielding_team_name=row["pitcher_team_name"].strip(),
        batter_id=row["batter_id"].strip(),
        batter_name=row["batter_name"].strip(),
        pitcher_id=row["pitcher_id"].strip(),
        pitcher_name=row["pitcher_name"].strip(),
        before=_state(row, "pre"),
        after=_state(row, "post"),
        is_starter=_flag(row, "is_starter"),
        is_sac_bunt_attempt=_flag(row, "is_sac_bunt_attempt"),
        is_sacrifice_hit=_flag(row, "is_sh"),
        is_bunt=_flag(row, "is_bunt"),
        is_pinch_hitter=_flag(row, "is_pinch_hitter"),
        is_intentional_walk=_flag(row, "is_ibb"),
        stolen_base=_flag(row, "is_runner_1b_sb") or _flag(row, "is_runner_2b_sb"),
        caught_stealing=_flag(row, "is_runner_1b_cs") or _flag(row, "is_runner_2b_cs"),
        situation_changed=_flag(row, "change_situation"),
    )


def pitching_changes(appearances: Iterable[PlateAppearance]) -> set[int]:
    """Return the indices of appearances that open a new pitcher's outing.

    DataStadium has no pitching-change column, so a change is derived: within a
    game, the fielding team's pitcher id differing from that team's previous
    pitcher marks a relief appearance. The starter's first batter is excluded,
    since taking the mound to begin a game is not a mid-game decision.
    """

    previous: dict[tuple[str, str], str] = {}
    changes: set[int] = set()
    for index, appearance in enumerate(appearances):
        key = (appearance.game_id, appearance.fielding_team_id)
        last = previous.get(key)
        if last is not None and last != appearance.pitcher_id:
            changes.add(index)
        previous[key] = appearance.pitcher_id
    return changes


def read_plate_appearances(path: str | Path) -> list[PlateAppearance]:
    """Read 打席イベントデータ (or 1球イベントデータ) from a CSV file.

    The published files are UTF-8 with a byte-order mark, which ``utf-8-sig``
    strips so the first column name parses correctly.
    """

    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames)
        return [_to_plate_appearance(row) for row in reader]


def _require_columns(fieldnames: Iterable[str] | None) -> None:
    present = set(fieldnames or ())
    missing = [column for column in REQUIRED_COLUMNS if column not in present]
    if missing:
        raise SchemaError(f"input is missing required columns: {', '.join(missing)}")


def decision_events(appearances: Iterable[PlateAppearance]) -> Iterator[PlateAppearance]:
    """Yield the appearances that represent a manager's choice.

    A bunt attempt, an intentional walk, a pinch hitter, a steal and a pitching
    change are the five decision types the project scores first. Everything else
    is a player outcome rather than a decision, so it is skipped here even though
    it still feeds the win-probability model.
    """

    ordered = list(appearances)
    relief = pitching_changes(ordered)
    for index, appearance in enumerate(ordered):
        if (
            appearance.is_sac_bunt_attempt
            or appearance.is_intentional_walk
            or appearance.is_pinch_hitter
            or appearance.stolen_base
            or appearance.caught_stealing
            or index in relief
        ):
            yield appearance
