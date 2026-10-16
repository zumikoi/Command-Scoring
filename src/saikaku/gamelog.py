"""The play-by-play section of a game note, and what follows from it.

A note may carry ``## 試合経過``: one row per plate appearance (and per stolen
base attempt) in order, with 回, 表裏, 打者, 投手 and 結果. From it the scorer
works out, for each decision, everything that had happened before it: each
player's line so far today, and how many batters the pitcher had faced. It
also gives each player's line for the whole game, which turns season totals
read after the game back into totals as of the first pitch.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .abilities import StatLine

#: 結果 words and what they count as. ``IBB`` is a plate appearance kept out
#: of form; ``SB``/``CS`` are not plate appearances (the 打者 column names the
#: runner).
RESULTS = {
    "三振": "K", "見逃し三振": "K", "空振り三振": "K", "振り逃げ": "K",
    "四球": "BB", "死球": "HBP", "敬遠": "IBB",
    "単打": "1B", "安打": "1B", "内野安打": "1B",
    "二塁打": "2B", "三塁打": "3B", "本塁打": "HR",
    "凡打": "OUT", "ゴロ": "OUT", "フライ": "OUT", "ライナー": "OUT", "併殺": "OUT",
    "犠打": "OUT", "犠飛": "OUT", "失策": "OUT", "野選": "OUT", "打撃妨害": "OUT",
    "盗塁": "SB", "盗塁死": "CS",
}


class LogFormatError(ValueError):
    """Raised when a 試合経過 row cannot be read."""


@dataclass(frozen=True)
class LogEntry:
    inning: int
    half: str
    batter: str
    pitcher: str
    result: str

    @property
    def code(self) -> str:
        return RESULTS[self.result]

    @property
    def is_plate_appearance(self) -> bool:
        return self.code not in ("SB", "CS")


def parse_log(rows: Iterable[Mapping[str, str]]) -> tuple[LogEntry, ...]:
    entries = []
    for number, row in enumerate(rows, start=1):
        result = row.get("結果", "").strip()
        if result not in RESULTS:
            raise LogFormatError(
                f"試合経過 {number}行目: 結果「{result}」は {'・'.join(RESULTS)} のどれかで書いてください"
            )
        half = {"表": "top", "裏": "bottom"}.get(row.get("表裏", "").strip())
        if half is None:
            raise LogFormatError(f"試合経過 {number}行目: 表裏は「表」か「裏」で書いてください")
        try:
            inning = int(row.get("回", "").strip())
        except ValueError:
            raise LogFormatError(f"試合経過 {number}行目: 回は数字で書いてください") from None
        entries.append(LogEntry(inning, half, row.get("打者", "").strip(),
                                row.get("投手", "").strip(), result))
    return tuple(entries)


def _line(codes: Counter[str], plate_appearances: int, split: bool) -> StatLine:
    walks = codes["BB"] + codes["IBB"]
    return StatLine(
        pa=plate_appearances,
        h=codes["1B"] + codes["2B"] + codes["3B"] + codes["HR"],
        hr=codes["HR"],
        bb=walks,
        hbp=codes["HBP"],
        so=codes["K"],
        doubles=codes["2B"] if split else None,
        triples=codes["3B"] if split else None,
        ibb=codes["IBB"],
    )


def batting_line(entries: Sequence[LogEntry], name: str) -> StatLine:
    mine = [e for e in entries if e.batter == name and e.is_plate_appearance]
    return _line(Counter(e.code for e in mine), len(mine), split=True)


def pitching_line(entries: Sequence[LogEntry], name: str) -> StatLine:
    mine = [e for e in entries if e.pitcher == name and e.is_plate_appearance]
    return _line(Counter(e.code for e in mine), len(mine), split=False)


def steals(entries: Sequence[LogEntry], name: str) -> tuple[int, int]:
    codes = Counter(e.code for e in entries if e.batter == name and not e.is_plate_appearance)
    return codes["SB"], codes["CS"]


def batters_faced(entries: Sequence[LogEntry], pitcher: str) -> int:
    return sum(1 for e in entries if e.pitcher == pitcher and e.is_plate_appearance)


def subtract(season: StatLine, game: StatLine, what: str) -> StatLine:
    """Season totals after a game, minus that game: totals as of the first pitch."""

    def minus(a: int | None, b: int | None) -> int | None:
        return None if a is None else a - (b or 0)

    try:
        return StatLine(
            pa=season.pa - game.pa,
            h=season.h - game.h,
            hr=season.hr - game.hr,
            bb=season.bb - game.bb,
            hbp=season.hbp - game.hbp,
            so=season.so - game.so,
            doubles=minus(season.doubles, game.doubles),
            triples=minus(season.triples, game.triples),
            ibb=season.ibb - game.ibb,
        )
    except ValueError as error:
        raise LogFormatError(f"{what}: 成績から試合経過を引くと矛盾します（{error}）") from None


def find_decision(
    entries: Sequence[LogEntry], start: int, inning: int, half: str, batter: str
) -> int | None:
    """Index of the plate appearance a decision was made at, searching onward."""

    for index in range(start, len(entries)):
        e = entries[index]
        if (e.inning, e.half, e.batter) == (inning, half, batter) and e.is_plate_appearance:
            return index
    return None
