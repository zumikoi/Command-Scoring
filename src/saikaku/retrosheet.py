"""Read base-out transitions from Retrosheet's parsed play-by-play files.

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


class SchemaError(ValueError):
    """Raised when a file does not have the columns this reader relies on."""


def _occupied(value: str) -> bool:
    """A base column holds the runner's id when occupied and is blank otherwise."""

    return value.strip() not in {"", "0"}


def _bases(row: dict[str, str], suffix: str) -> int:
    return (
        int(_occupied(row[f"br1_{suffix}"]))
        | int(_occupied(row[f"br2_{suffix}"])) << 1
        | int(_occupied(row[f"br3_{suffix}"])) << 2
    )


def _read_csv(handle: TextIO) -> Iterator[Transition]:
    reader = csv.DictReader(handle)
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or ())]
    if missing:
        raise SchemaError(f"missing required columns: {', '.join(missing)}")
    for row in reader:
        outs_pre = int(row["outs_pre"])
        if outs_pre >= 3:
            continue
        yield Transition(
            outs_pre=outs_pre,
            bases_pre=_bases(row, "pre"),
            outs_post=int(row["outs_post"]),
            bases_post=_bases(row, "post"),
            runs=int(row["runs"] or 0),
        )


def read_transitions(path: str | Path) -> Iterator[Transition]:
    """Yield transitions from a plays CSV, or from every CSV inside a zip."""

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


def read_all(paths: Iterable[str | Path]) -> Iterator[Transition]:
    for path in paths:
        yield from read_transitions(path)
