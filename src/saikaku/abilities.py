"""Batter and pitcher abilities as multipliers on plate-appearance outcomes.

An ability is a ratio to the league for each outcome: a batter who homers
twice as often as the league has ``HR = 2.0``. Ratios rather than raw rates are
what let an NPB player's line, measured against the NPB league, be applied to
transitions estimated from MLB play-by-play.

Stat lines are typed in by the user; nothing here fetches player data. Small
samples are pulled toward the league with pseudo plate appearances set near the
point where each rate becomes about half signal, half noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

#: Plate-appearance outcomes. Walks include hit-by-pitch and exclude
#: intentional walks; OUT is everything else, errors and sacrifices included.
EVENTS = ("K", "BB", "1B", "2B", "3B", "HR", "OUT")

#: Pseudo plate appearances of league-average performance added to a line.
BATTER_PSEUDO_PA = {"K": 60, "BB": 120, "1B": 290, "2B": 1600, "3B": 1600, "HR": 170}
PITCHER_PSEUDO_PA = {"K": 70, "BB": 170, "HR": 1320}
#: Pitchers have little control over hits on balls in play; regress hard.
PITCHER_PSEUDO_BIP = 2000

#: Japanese column names accepted in decision records and the demo.
BATTER_KEYS = {
    "pa": "打席", "h": "安打", "doubles": "二塁打", "triples": "三塁打",
    "hr": "本塁打", "bb": "四球", "hbp": "死球", "so": "三振", "ibb": "敬遠",
}
PITCHER_KEYS = {
    "pa": "打者", "h": "被安打", "hr": "被本塁打", "bb": "与四球",
    "hbp": "与死球", "so": "奪三振", "ibb": "敬遠",
}


@dataclass(frozen=True)
class Ability:
    ratios: Mapping[str, float] = field(default_factory=lambda: {e: 1.0 for e in EVENTS})
    label: str = "リーグ平均"

    def ratio(self, event: str) -> float:
        return self.ratios.get(event, 1.0)

    @property
    def is_average(self) -> bool:
        return all(abs(self.ratio(e) - 1.0) < 1e-12 for e in EVENTS)


AVERAGE = Ability()


@dataclass(frozen=True)
class StatLine:
    """Season totals. Doubles and triples may be unknown, as on pitcher lines."""

    pa: int
    h: int
    hr: int
    bb: int
    hbp: int
    so: int
    doubles: int | None = None
    triples: int | None = None
    ibb: int = 0

    def __post_init__(self) -> None:
        counts = (self.pa, self.h, self.hr, self.bb, self.hbp, self.so, self.ibb)
        if any(value < 0 for value in counts):
            raise ValueError("stat line counts must not be negative")
        extra = (self.doubles or 0) + (self.triples or 0) + self.hr
        if extra > self.h:
            raise ValueError("extra-base hits exceed hits")
        if self.ibb > self.bb:
            raise ValueError("intentional walks exceed walks")
        if self.h + self.bb + self.hbp + self.so > self.pa:
            raise ValueError("hits, walks and strikeouts exceed plate appearances")

    @property
    def unintentional_pa(self) -> int:
        return self.pa - self.ibb

    def counts(self) -> dict[str, int | None]:
        """Outcome counts, with 2B and 3B as None when the line lacks them."""

        has_split = self.doubles is not None and self.triples is not None
        singles = self.h - self.hr - (self.doubles or 0) - (self.triples or 0)
        return {
            "K": self.so,
            "BB": self.bb - self.ibb + self.hbp,
            "1B": singles if has_split else None,
            "2B": self.doubles if has_split else None,
            "3B": self.triples if has_split else None,
            "HR": self.hr,
            "H": self.h,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object], keys: Mapping[str, str]) -> "StatLine":
        """Read a line keyed by English field names or their Japanese labels."""

        def get(name: str) -> int | None:
            for key in (name, keys.get(name)):
                if key is not None and raw.get(key) not in (None, ""):
                    return int(raw[key])
            return None

        values = {name: get(name) for name in keys}
        missing = [keys[name] for name in ("pa", "h", "hr", "bb", "so") if values[name] is None]
        if missing:
            raise ValueError(f"stat line is missing: {', '.join(missing)}")
        return cls(
            pa=values["pa"],
            h=values["h"],
            hr=values["hr"],
            bb=values["bb"],
            hbp=values["hbp"] or 0,
            so=values["so"],
            doubles=values.get("doubles"),
            triples=values.get("triples"),
            ibb=values["ibb"] or 0,
        )


def league_rates(line: StatLine) -> dict[str, float]:
    """Per-PA outcome rates of a league line, which must split 2B and 3B."""

    counts = line.counts()
    if counts["2B"] is None:
        raise ValueError("the league line needs doubles and triples")
    pa = line.unintentional_pa
    rates = {event: counts[event] / pa for event in EVENTS if event != "OUT"}
    rates["OUT"] = 1.0 - sum(rates.values())
    return rates


def _ratios(rates: dict[str, float], league: Mapping[str, float], label: str) -> Ability:
    rates = dict(rates)
    rates["OUT"] = 1.0 - sum(rates.values())
    if rates["OUT"] <= 0:
        raise ValueError("stat line leaves no outs")
    return Ability({event: rates[event] / league[event] for event in EVENTS}, label)


def batter_ability(line: StatLine, league: Mapping[str, float], label: str = "") -> Ability:
    counts = line.counts()
    pa = line.unintentional_pa
    if counts["2B"] is None:
        # Without a split, assume the league's mix of singles, doubles, triples.
        non_hr = counts["H"] - counts["HR"]
        hit_mix = sum(league[e] for e in ("1B", "2B", "3B"))
        counts = {**counts, **{e: non_hr * league[e] / hit_mix for e in ("1B", "2B", "3B")}}
    rates = {
        event: (counts[event] + BATTER_PSEUDO_PA[event] * league[event])
        / (pa + BATTER_PSEUDO_PA[event])
        for event in BATTER_PSEUDO_PA
    }
    return _ratios(rates, league, label or "成績から推定")


def pitcher_ability(line: StatLine, league: Mapping[str, float], label: str = "") -> Ability:
    counts = line.counts()
    pa = line.unintentional_pa
    rates = {
        event: (counts[event] + PITCHER_PSEUDO_PA[event] * league[event])
        / (pa + PITCHER_PSEUDO_PA[event])
        for event in PITCHER_PSEUDO_PA
    }
    # Hits on balls in play, regressed as one rate, then split like the league.
    league_bip = 1.0 - league["K"] - league["BB"] - league["HR"]
    league_babip = (league["1B"] + league["2B"] + league["3B"]) / league_bip
    bip = max(pa - counts["K"] - counts["BB"] - counts["HR"], 0)
    babip = (counts["H"] - counts["HR"] + PITCHER_PSEUDO_BIP * league_babip) / (
        bip + PITCHER_PSEUDO_BIP
    )
    expected_bip = 1.0 - rates["K"] - rates["BB"] - rates["HR"]
    for event in ("1B", "2B", "3B"):
        rates[event] = expected_bip * babip * league[event] / (league_babip * league_bip)
    return _ratios(rates, league, label or "成績から推定")


def matchup(
    base_rates: Mapping[str, float], batter: Ability, pitcher: Ability
) -> dict[str, float]:
    """Outcome probabilities for one batter against one pitcher.

    Multiplying the league odds by both players' ratios and renormalising is
    the multinomial form of the log5 method.
    """

    weights = {e: base_rates.get(e, 0.0) * batter.ratio(e) * pitcher.ratio(e) for e in EVENTS}
    total = sum(weights.values())
    return {e: w / total for e, w in weights.items()}
