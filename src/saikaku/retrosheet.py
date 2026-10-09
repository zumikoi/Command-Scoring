"""Read plays from Retrosheet's parsed play-by-play files.

The files are the per-season ``<year>plays.zip`` downloads listed at
https://www.retrosheet.org/downloads/plays.html. Retrosheet permits any use on
condition of the attribution in :data:`ATTRIBUTION`, which must accompany
anything published from this data.

The data is MLB, not NPB. It stands in for NPB's run environment until a
permitted NPB source exists; see DATA_SOURCES.md.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, TextIO

from .runs import Transition

ATTRIBUTION = (
    "The information used here was obtained free of charge from and is "
    "copyrighted by Retrosheet. Interested parties may contact Retrosheet at "
    '"www.retrosheet.org".'
)

REQUIRED_COLUMNS = (
    "outs_pre",
    "outs_post",
    "br1_pre",
    "br2_pre",
    "br3_pre",
    "br1_post",
    "br2_post",
    "br3_post",
    "runs",
)

#: Pitch codes for a bunt attempt: ``L`` is a foul bunt, ``M`` a missed one.
_BUNT_PITCHES = frozenset("LM")


class SchemaError(ValueError):
    """Raised when a file does not have the columns this reader relies on."""


@dataclass(frozen=True)
class Play:
    """One play record with the flags that identify a manager's tactic.

    Flag columns missing from a file read as false, so a file with only the
    required columns still yields every transition.
    """

    transition: Transition
    plate_appearance: bool = False
    #: A bunt in play, or a strikeout on a foul or missed bunt.
    bunt_attempt: bool = False
    intentional_walk: bool = False
    #: The base a lone steal attempt targeted (2 or 3), made between pitches.
    steal_target: int | None = None
    #: The plate appearance's outcome as one of ``abilities.EVENTS``; None for
    #: non-PA plays, bunts and intentional walks.
    event: str | None = None
    batter: str = ""
    pitcher: str = ""
    season: str = ""


def _occupied(value: str) -> bool:
    """A base column holds the runner's id when occupied and is blank otherwise."""

    return value.strip() not in {"", "0"}


def _bases(row: dict[str, str], suffix: str) -> int:
    return (
        int(_occupied(row[f"br1_{suffix}"]))
        | int(_occupied(row[f"br2_{suffix}"])) << 1
        | int(_occupied(row[f"br3_{suffix}"])) << 2
    )


def _flag(row: dict[str, str], column: str) -> bool:
    return row.get(column, "").strip() == "1"


def _steal_target(row: dict[str, str]) -> int | None:
    """Return the base of a single steal attempt that was the whole play.

    Steals folded into a plate appearance (a strikeout with a stolen base) and
    double steals are excluded; neither isolates the decision to run.
    """

    if _flag(row, "pa"):
        return None
    targets = {
        base
        for base, columns in ((2, ("sb2", "cs2")), (3, ("sb3", "cs3")), (4, ("sbh", "csh")))
        if any(_flag(row, column) for column in columns)
    }
    if len(targets) != 1:
        return None
    (target,) = targets
    return target if target in (2, 3) else None


#: Outcome columns checked in order; a plate appearance has at most one set.
_EVENT_COLUMNS = (
    ("k", "K"), ("walk", "BB"), ("hbp", "BB"),
    ("single", "1B"), ("double", "2B"), ("triple", "3B"), ("hr", "HR"),
)


def _event(row: dict[str, str]) -> str:
    for column, event in _EVENT_COLUMNS:
        if _flag(row, column):
            return event
    return "OUT"


def _to_play(row: dict[str, str]) -> Play:
    plate_appearance = _flag(row, "pa")
    bunt_attempt = plate_appearance and (
        _flag(row, "bunt")
        or (_flag(row, "k") and row.get("pitches", "")[-1:] in _BUNT_PITCHES)
    )
    intentional_walk = _flag(row, "iw")
    has_event = plate_appearance and not bunt_attempt and not intentional_walk
    return Play(
        transition=Transition(
            outs_pre=int(row["outs_pre"]),
            bases_pre=_bases(row, "pre"),
            outs_post=int(row["outs_post"]),
            bases_post=_bases(row, "post"),
            runs=int(row["runs"] or 0),
        ),
        plate_appearance=plate_appearance,
        bunt_attempt=bunt_attempt,
        intentional_walk=intentional_walk,
        steal_target=_steal_target(row),
        event=_event(row) if has_event else None,
        batter=row.get("batter", ""),
        pitcher=row.get("pitcher", ""),
        season=row.get("date", "")[:4],
    )


def _read_csv(handle: TextIO) -> Iterator[Play]:
    reader = csv.DictReader(handle)
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or ())]
    if missing:
        raise SchemaError(f"missing required columns: {', '.join(missing)}")
    for row in reader:
        # Postseason and All-Star games are played differently; keep the
        # regular season only when the file says which is which.
        if row.get("gametype", "regular") != "regular":
            continue
        if int(row["outs_pre"]) >= 3:
            continue
        yield _to_play(row)


def read_plays(path: str | Path) -> Iterator[Play]:
    """Yield plays from a plays CSV, or from every CSV inside a zip."""

    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".csv"):
                    with archive.open(name) as raw:
                        yield from _read_csv(io.TextIOWrapper(raw, encoding="utf-8-sig"))
        return
    with open(path, encoding="utf-8-sig", newline="") as handle:
        yield from _read_csv(handle)


def read_transitions(path: str | Path) -> Iterator[Transition]:
    return (play.transition for play in read_plays(path))


def read_all(paths: Iterable[str | Path]) -> Iterator[Play]:
    for path in paths:
        yield from read_plays(path)
