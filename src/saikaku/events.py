"""Plate-appearance outcomes by base-out state, adjusted for who is batting.

Each outcome (strikeout, walk, single and so on) has its own distribution of
next base-out states, estimated from play-by-play. The league's mix of outcomes
in a state is then reweighted for the batter and pitcher, and the result is
pushed forward through the next few batters in the order. Beyond them the
league-average win-probability model takes over.

Only plate appearances are modelled here. Steals, wild pitches and balks
between pitches are left out, which slightly understates scoring in the
lookahead; every option of a decision shares that, so comparisons hold.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .abilities import (
    AVERAGE,
    EVENTS,
    Ability,
    StatLine,
    batter_ability,
    head_to_head_factors,
    matchup,
    pitcher_ability,
    platoon_side,
)
from .retrosheet import Play
from .runs import base_index, state_key

DEFAULT_EVENTS = Path(__file__).with_name("data") / "events.json"

#: How many batters a decision is followed through before averages take over.
LINEUP_DEPTH = 3

#: Player-seasons below these are too noisy to place in a profile band.
PROFILE_MIN_BATTER_PA = 300
PROFILE_MIN_PITCHER_PA = 250

#: wOBA-style run weights, used only to rank players into profile bands.
_RANK_WEIGHTS = {"BB": 0.69, "1B": 0.89, "2B": 1.27, "3B": 1.62, "HR": 2.10}

#: (lower percentile, upper percentile, batter label, pitcher label), best first.
PROFILE_BANDS = (
    (0.0, 0.1, "強打者（上位10%）", "エース級（上位10%）"),
    (0.1, 0.3, "好打者（上位10〜30%）", "好投手（上位10〜30%）"),
    (0.3, 0.7, "平均的なレギュラー", "平均的な投手"),
    (0.7, 0.9, "やや非力（下位10〜30%）", "やや不安（下位10〜30%）"),
    (0.9, 1.0, "非力（下位10%）", "不安定（下位10%）"),
)

#: Pseudo plate appearances used when the data shows no head-to-head effect.
NO_SIGNAL_PSEUDO = 1_000_000

State = tuple[int, int]
End = tuple[int, int, int]  # outs, bases, runs
#: Looks up head-to-head multipliers for a batter and pitcher, if any.
PairLookup = Callable[[Ability, Ability], Mapping[str, float] | None]


@dataclass(frozen=True)
class EventTable:
    #: League outcome counts per base-out state.
    rates: dict[State, Counter[str]]
    #: Next-state counts per outcome and base-out state.
    transitions: dict[str, dict[State, Counter[End]]]
    league: dict[str, float]
    batter_profiles: tuple[Ability, ...] = ()
    pitcher_profiles: tuple[Ability, ...] = ()
    #: Per-outcome multipliers for "same" and "opposite" handedness.
    platoon: dict[str, dict[str, float]] = field(default_factory=dict)
    #: Pseudo plate appearances that regress a head-to-head record.
    h2h_pseudo: dict[str, float] = field(default_factory=dict)
    #: How the head-to-head pseudo counts were measured, for display.
    h2h_summary: dict = field(default_factory=dict)
    source: str = ""
    _cache: dict = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_plays(cls, plays: Iterable[Play], source: str = "") -> "EventTable":
        rates: dict[State, Counter[str]] = defaultdict(Counter)
        transitions: dict[str, dict[State, Counter[End]]] = {e: defaultdict(Counter) for e in EVENTS}
        batters: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        pitchers: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        sides: dict[str, Counter[str]] = defaultdict(Counter)
        pairs: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
        for play in plays:
            if play.event is None:
                continue
            t = play.transition
            start = (t.outs_pre, t.bases_pre)
            rates[start][play.event] += 1
            transitions[play.event][start][
                (t.outs_post, 0 if t.outs_post == 3 else t.bases_post, t.runs)
            ] += 1
            batters[(play.season, play.batter)][play.event] += 1
            pitchers[(play.season, play.pitcher)][play.event] += 1
            side = platoon_side(play.bat_hand, play.pit_hand)
            if side:
                sides[side][play.event] += 1
                pairs[(play.season, play.batter, play.pitcher, side)][play.event] += 1

        totals = Counter()
        for counter in rates.values():
            totals.update(counter)
        n = sum(totals.values())
        league = {e: totals[e] / n for e in EVENTS}
        platoon = {
            side: {e: counter[e] / sum(counter.values()) / league[e] for e in EVENTS}
            for side, counter in sides.items()
        }
        h2h_pseudo, h2h_summary = measure_head_to_head(pairs)
        return cls(
            rates={s: Counter(c) for s, c in rates.items()},
            transitions={e: {s: Counter(c) for s, c in by.items()} for e, by in transitions.items()},
            league=league,
            batter_profiles=_profiles(batters.values(), league, batting=True),
            pitcher_profiles=_profiles(pitchers.values(), league, batting=False),
            platoon=platoon,
            h2h_pseudo=h2h_pseudo,
            h2h_summary=h2h_summary,
            source=source,
        )

    def samples(self, outs: int, bases: int) -> int:
        return sum(self.rates.get((outs, bases), Counter()).values())

    def pair_expectation(self, batter: Ability, pitcher: Ability) -> dict[str, float]:
        """What the two players' abilities predict for each other, any state."""

        return matchup(self.league, batter, pitcher, self.platoon)

    def pair_factors(self, batter: Ability, pitcher: Ability, record: StatLine) -> dict[str, float]:
        """Head-to-head multipliers for a record between these two players."""

        return head_to_head_factors(
            record, self.pair_expectation(batter, pitcher), self.h2h_pseudo
        )

    def pa_outcomes(
        self,
        outs: int,
        bases: int,
        batter: Ability = AVERAGE,
        pitcher: Ability = AVERAGE,
        pair: Mapping[str, float] | None = None,
    ) -> dict[End, float]:
        """Next-state distribution of one plate appearance."""

        key = (outs, bases, id(batter), id(pitcher), id(pair))
        cached = self._cache.get(key)
        if cached is not None:
            return cached[0]
        counts = self.rates.get((outs, bases))
        if not counts:
            raise LookupError(f"no plate appearances observed from {state_key(outs, bases)}")
        total = sum(counts.values())
        probabilities = matchup(
            {e: counts[e] / total for e in EVENTS}, batter, pitcher, self.platoon, pair
        )
        result: dict[End, float] = defaultdict(float)
        covered = 0.0
        for event, p in probabilities.items():
            ends = self.transitions[event].get((outs, bases))
            if not ends or p == 0.0:
                continue
            covered += p
            n = sum(ends.values())
            for end, count in ends.items():
                result[end] += p * count / n
        result = {end: p / covered for end, p in result.items()}
        self._cache[key] = (result, batter, pitcher, pair)  # keep keys alive for id()
        return result

    def forward(
        self,
        outs: int,
        bases: int,
        lineup: Sequence[Ability],
        pitcher: Ability = AVERAGE,
        pairs: PairLookup | None = None,
    ) -> dict[End, float]:
        """Distribution of (outs, bases, runs) after the given batters have batted.

        The half inning may end before the lineup is used up; a third out is
        absorbing.
        """

        current: dict[End, float] = {(outs, bases, 0): 1.0}
        for batter in lineup:
            pair = pairs(batter, pitcher) if pairs else None
            following: dict[End, float] = defaultdict(float)
            for (o, b, r), p in current.items():
                if o == 3:
                    following[(o, b, r)] += p
                    continue
                for (o2, b2, r2), q in self.pa_outcomes(o, b, batter, pitcher, pair).items():
                    following[(o2, b2, r + r2)] += p * q
            current = following
        return dict(current)

    def to_json(self) -> str:
        return json.dumps(
            {
                "source": self.source,
                "league": self.league,
                "rates": {state_key(*s): dict(c) for s, c in sorted(self.rates.items())},
                "transitions": {
                    e: {
                        state_key(*s): [[o, b, r, n] for (o, b, r), n in sorted(c.items())]
                        for s, c in sorted(by.items())
                    }
                    for e, by in self.transitions.items()
                },
                "profiles": {
                    "batter": [{"label": a.label, "ratios": dict(a.ratios)} for a in self.batter_profiles],
                    "pitcher": [{"label": a.label, "ratios": dict(a.ratios)} for a in self.pitcher_profiles],
                },
                "platoon": self.platoon,
                "h2h_pseudo": self.h2h_pseudo,
                "h2h_summary": self.h2h_summary,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, text: str) -> "EventTable":
        raw = json.loads(text)
        return cls(
            rates={_state(k): Counter(v) for k, v in raw["rates"].items()},
            transitions={
                e: {_state(k): Counter({(o, b, r): n for o, b, r, n in rows}) for k, rows in by.items()}
                for e, by in raw["transitions"].items()
            },
            league=raw["league"],
            batter_profiles=tuple(Ability(p["ratios"], p["label"]) for p in raw["profiles"]["batter"]),
            pitcher_profiles=tuple(Ability(p["ratios"], p["label"]) for p in raw["profiles"]["pitcher"]),
            platoon=raw.get("platoon", {}),
            h2h_pseudo=raw.get("h2h_pseudo", {}),
            h2h_summary=raw.get("h2h_summary", {}),
            source=raw.get("source", ""),
        )

    @classmethod
    def load(cls, path: str | Path = DEFAULT_EVENTS) -> "EventTable":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def profile(self, label: str, batting: bool) -> Ability:
        if label == AVERAGE.label:
            return AVERAGE
        for ability in self.batter_profiles if batting else self.pitcher_profiles:
            if ability.label == label:
                return ability
        raise KeyError(f"unknown profile: {label}")


def _state(key: str) -> State:
    outs, mask = key.split("-")
    return (int(outs), base_index(tuple(char == "1" for char in mask)))


def _line(counts: Mapping[str, int], batting: bool) -> StatLine:
    hits = counts["1B"] + counts["2B"] + counts["3B"] + counts["HR"]
    return StatLine(
        pa=sum(counts.values()),
        h=hits,
        hr=counts["HR"],
        bb=counts["BB"],
        hbp=0,
        so=counts["K"],
        doubles=counts["2B"] if batting else None,
        triples=counts["3B"] if batting else None,
    )


def _profiles(
    players: Iterable[Counter[str]], league: Mapping[str, float], batting: bool
) -> tuple[Ability, ...]:
    """Average the regressed abilities of player-seasons in each quality band."""

    minimum = PROFILE_MIN_BATTER_PA if batting else PROFILE_MIN_PITCHER_PA
    estimate = batter_ability if batting else pitcher_ability
    abilities = [
        estimate(_line(counts, batting), league)
        for counts in players
        if sum(counts.values()) >= minimum
    ]
    if not abilities:
        return ()

    def quality(ability: Ability) -> float:
        return sum(w * league[e] * ability.ratio(e) for e, w in _RANK_WEIGHTS.items())

    # Best first: high quality for batters, low quality allowed for pitchers.
    ranked = sorted(abilities, key=quality, reverse=batting)
    profiles = []
    for low, high, batter_label, pitcher_label in PROFILE_BANDS:
        band = ranked[int(low * len(ranked)) : max(int(high * len(ranked)), int(low * len(ranked)) + 1)]
        ratios = {e: sum(a.ratio(e) for a in band) / len(band) for e in EVENTS}
        profiles.append(Ability(ratios, batter_label if batting else pitcher_label))
    return tuple(profiles)


#: Outcome groups measured for head-to-head effects. Doubles and triples are
#: too rare to measure alone, so hits on balls in play are measured together.
H2H_GROUPS = {"K": ("K",), "BB": ("BB",), "HR": ("HR",), "H": ("1B", "2B", "3B")}


def measure_head_to_head(
    pairs: Mapping[tuple[str, str, str, str], Counter[str]],
) -> tuple[dict[str, float], dict]:
    """Find how far a batter-pitcher record should move a prediction.

    The latest season is held out. For every pair that met both before and in
    it, the earlier seasons give the expectation (both players' abilities and
    the platoon effect) and the pair's own earlier record. The pseudo plate
    appearances that best predict the held-out plate appearances, by log loss,
    are the answer. If no amount of the record beats ignoring it, there is no
    head-to-head effect to use.
    """

    seasons = sorted({season for season, *_ in pairs})
    no_signal = {e: float(NO_SIGNAL_PSEUDO) for e in EVENTS}
    if len(seasons) < 2:
        return no_signal, {"note": "対戦成績の効きを測るには2シーズン以上が必要"}
    test_season = seasons[-1]

    train: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    test: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    batter_totals: dict[str, Counter[str]] = defaultdict(Counter)
    pitcher_totals: dict[str, Counter[str]] = defaultdict(Counter)
    side_totals: dict[str, Counter[str]] = defaultdict(Counter)
    for (season, batter, pitcher, side), counts in pairs.items():
        if season == test_season:
            test[(batter, pitcher, side)].update(counts)
            continue
        train[(batter, pitcher, side)].update(counts)
        batter_totals[batter].update(counts)
        pitcher_totals[pitcher].update(counts)
        side_totals[side].update(counts)

    totals = sum(side_totals.values(), Counter())
    n = sum(totals.values())
    league = {e: totals[e] / n for e in EVENTS}
    platoon = {
        side: {e: c[e] / sum(c.values()) / league[e] for e in EVENTS}
        for side, c in side_totals.items()
    }

    batter_cache: dict[str, Ability] = {}
    pitcher_cache: dict[str, Ability] = {}
    cases = []  # (expected rate, earlier count, earlier PA, held-out count, held-out PA) per group
    for key, held_out in test.items():
        earlier = train.get(key)
        if not earlier:
            continue
        batter, pitcher, side = key
        if batter not in batter_cache:
            batter_cache[batter] = batter_ability(_line(batter_totals[batter], True), league)
        if pitcher not in pitcher_cache:
            pitcher_cache[pitcher] = pitcher_ability(_line(pitcher_totals[pitcher], False), league)
        expected = matchup(
            league, batter_cache[batter], pitcher_cache[pitcher], head_to_head=platoon.get(side)
        )
        m, t_n = sum(earlier.values()), sum(held_out.values())
        cases.append({
            group: (
                sum(expected[e] for e in events),
                sum(earlier[e] for e in events),
                m,
                sum(held_out[e] for e in events),
                t_n,
            )
            for group, events in H2H_GROUPS.items()
        })

    def loss(group: str, k: float | None) -> float:
        total = 0.0
        for case in cases:
            mu, x, m, y, t_n = case[group]
            q = mu if k is None else (x + k * mu) / (m + k)
            q = min(max(q, 1e-9), 1 - 1e-9)
            total -= y * math.log(q) + (t_n - y) * math.log(1 - q)
        return total

    pseudo: dict[str, float] = {}
    gains: dict[str, float] = {}
    for group, events in H2H_GROUPS.items():
        baseline = loss(group, None)
        # Golden-section search on log10(k) over 1 .. 1,000,000.
        low, high = 0.0, math.log10(NO_SIGNAL_PSEUDO)
        ratio = (math.sqrt(5) - 1) / 2
        a, b = high - ratio * (high - low), low + ratio * (high - low)
        fa, fb = loss(group, 10 ** a), loss(group, 10 ** b)
        for _ in range(40):
            if fa < fb:
                high, b, fb = b, a, fa
                a = high - ratio * (high - low)
                fa = loss(group, 10 ** a)
            else:
                low, a, fa = a, b, fb
                b = low + ratio * (high - low)
                fb = loss(group, 10 ** b)
        best = 10 ** ((low + high) / 2)
        best_loss = loss(group, best)
        if best_loss >= baseline:
            best, best_loss = float(NO_SIGNAL_PSEUDO), baseline
        for e in events:
            pseudo[e] = best
        gains[group] = baseline - best_loss
    pseudo["OUT"] = float(NO_SIGNAL_PSEUDO)  # derived, never regressed directly

    summary = {
        "held_out_season": test_season,
        "pairs": len(cases),
        "held_out_pa": sum(case["K"][4] for case in cases),
        "log_loss_gain": gains,
    }
    return pseudo, summary
