"""Build a self-contained HTML demo of the model.

    python -m saikaku.demo [--out demo/index.html]

The league-average win probability of every state is computed here. Player
matchups are too many to tabulate, so the page repeats the plate-appearance
lookahead of :mod:`saikaku.events` in JavaScript. To keep the two in step, a
set of reference evaluations computed in Python is embedded and the page
checks itself against them when it loads.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .abilities import (
    AVERAGE,
    BATTER_PSEUDO_PA,
    EVENTS,
    PITCHER_PSEUDO_BIP,
    PITCHER_PSEUDO_PA,
    StatLine,
    batter_ability,
    pitcher_ability,
)
from .events import LINEUP_DEPTH, EventTable
from .model import GameState, WinProbabilityModel
from .retrosheet import ATTRIBUTION
from .tactics import (
    DECISION_TYPES,
    ESTIMATED,
    MIN_SAMPLES,
    TACTIC_NAMES,
    Matchup,
    TacticTable,
    evaluate,
)

TEMPLATE = Path(__file__).with_name("demo_template.html")
INNINGS = range(1, 13)
HALVES = ("top", "bottom")
#: Home-minus-away margins tabulated; wider margins are clamped to these.
MAX_DIFF = 10

#: Reference evaluations the page must reproduce. Abilities are profile
#: labels, or stat lines measured against the fitted league.
REFERENCE_CASES = (
    ("送りバント", (7, "top", 0, 1, 3, 3), {"lineup": ["非力（下位10%）", "強打者（上位10%）"]}),
    ("送りバント", (5, "bottom", 0, 3, 2, 4), {"pitcher": "エース級（上位10%）"}),
    ("二盗", (8, "top", 1, 1, 2, 2), {"lineup": ["好打者（上位10〜30%）"]}),
    ("三盗", (6, "bottom", 0, 2, 1, 1), {}),
    ("敬遠", (9, "bottom", 1, 2, 3, 2), {"lineup": ["強打者（上位10%）", "非力（下位10%）"]}),
    ("代打", (8, "bottom", 2, 3, 4, 3), {
        "lineup": ["非力（下位10%）"],
        "pinch_hitter": {"pa": 400, "h": 110, "doubles": 22, "triples": 1, "hr": 22,
                         "bb": 45, "hbp": 4, "so": 95},
    }),
    ("継投", (7, "top", 1, 5, 3, 4), {
        "pitcher": "不安定（下位10%）",
        "reliever": {"pa": 250, "h": 45, "hr": 4, "bb": 18, "hbp": 2, "so": 85},
    }),
)


def _states(max_outs: int):
    for inning in INNINGS:
        for half in HALVES:
            for outs in range(max_outs + 1):
                for bases in range(8):
                    for diff in range(-MAX_DIFF, MAX_DIFF + 1):
                        home, away = max(diff, 0), max(-diff, 0)
                        runners = (bool(bases & 1), bool(bases & 2), bool(bases & 4))
                        yield GameState(inning, half, outs, home, away, runners)


def _ability(spec, batting: bool, events: EventTable):
    if spec is None:
        return None
    if isinstance(spec, str):
        return events.profile(spec, batting)
    estimate = batter_ability if batting else pitcher_ability
    return estimate(StatLine(**spec), events.league)


def _reference(model: WinProbabilityModel, table: TacticTable, events: EventTable) -> list:
    cases = []
    for name, (inning, half, outs, bases, away, home), players in REFERENCE_CASES:
        runners = (bool(bases & 1), bool(bases & 2), bool(bases & 4))
        state = GameState(inning, half, outs, home, away, runners)
        matchup = Matchup(
            lineup=tuple(_ability(s, True, events) for s in players.get("lineup", [])),
            pitcher=_ability(players.get("pitcher"), False, events) or AVERAGE,
            pinch_hitter=_ability(players.get("pinch_hitter"), True, events),
            reliever=_ability(players.get("reliever"), False, events),
        )
        ev = evaluate(name, state, model, table, events, matchup)
        cases.append({
            "type": name,
            "state": {"inning": inning, "half": half, "outs": outs, "bases": bases,
                      "away": away, "home": home},
            "players": players,
            "expected": [ev.chosen_probability, ev.alternative_probability],
        })
    return cases


def build_data(model: WinProbabilityModel, table: TacticTable, events: EventTable) -> dict:
    wp, home_win, tie = [], [], []
    for state in _states(3):
        outcome = model.outcome(state)
        wp.append(round(model.probability(state), 6))
        home_win.append(round(outcome.home_win, 4))
        tie.append(round(outcome.tie, 4))

    def key(outs: int, bases: int) -> str:
        return f"{outs}{bases}"

    return {
        "maxDiff": MAX_DIFF,
        "innings": len(INNINGS),
        "depth": LINEUP_DEPTH,
        "minSamples": MIN_SAMPLES,
        "wp": wp,
        "homeWin": home_win,
        "tie": tie,
        "decisions": {
            name: {"chosen": kind.chosen, "alternative": kind.alternative,
                   "byOffense": kind.by_offense, "endsPa": kind.ends_plate_appearance}
            for name, kind in DECISION_TYPES.items()
        },
        "tacticNames": TACTIC_NAMES,
        "tactics": {
            tactic: {
                key(*state): [[o, b, r, n] for (o, b, r), n in counter.items()]
                for state, counter in table.counts[tactic].items()
            }
            for tactic in ESTIMATED
        },
        "events": {
            "names": list(EVENTS),
            "league": events.league,
            "rates": {key(*s): dict(c) for s, c in events.rates.items()},
            "transitions": {
                e: {key(*s): [[o, b, r, n] for (o, b, r), n in c.items()] for s, c in by.items()}
                for e, by in events.transitions.items()
            },
        },
        "pseudo": {"batter": BATTER_PSEUDO_PA, "pitcher": PITCHER_PSEUDO_PA,
                   "pitcherBip": PITCHER_PSEUDO_BIP},
        "profiles": {
            "batter": [{"label": a.label, "ratios": dict(a.ratios)} for a in events.batter_profiles],
            "pitcher": [{"label": a.label, "ratios": dict(a.ratios)} for a in events.pitcher_profiles],
        },
        "reference": _reference(model, table, events),
        "attribution": ATTRIBUTION,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("demo/index.html"))
    args = parser.parse_args()

    data = build_data(WinProbabilityModel.load_default(), TacticTable.load(), EventTable.load())
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"{args.out} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
