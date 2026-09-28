"""Build a self-contained HTML demo of the model.

    python -m saikaku.demo [--out demo/index.html]

Every value the page shows is computed here, so the browser only looks them
up. The page has no network dependencies and can be opened from disk.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .model import GameState, WinProbabilityModel
from .retrosheet import ATTRIBUTION
from .runs import base_index
from .tactics import (
    DECISION_TYPES,
    ESTIMATED,
    InsufficientData,
    TacticTable,
    evaluate,
)

TEMPLATE = Path(__file__).with_name("demo_template.html")
INNINGS = range(1, 13)
HALVES = ("top", "bottom")
#: Home-minus-away margins the page offers; wider margins are clamped to these.
MAX_DIFF = 10
#: Outcomes rarer than this are folded into "other" in the breakdown.
MIN_SHARE = 0.01


def _states(max_outs: int):
    for inning in INNINGS:
        for half in HALVES:
            for outs in range(max_outs + 1):
                for bases in range(8):
                    for diff in range(-MAX_DIFF, MAX_DIFF + 1):
                        home, away = max(diff, 0), max(-diff, 0)
                        runners = (bool(bases & 1), bool(bases & 2), bool(bases & 4))
                        yield GameState(inning, half, outs, home, away, runners)


def build_data(model: WinProbabilityModel, table: TacticTable) -> dict:
    wp, home_win, tie = [], [], []
    for state in _states(3):
        outcome = model.outcome(state)
        wp.append(round(model.probability(state), 4))
        home_win.append(round(outcome.home_win, 4))
        tie.append(round(outcome.tie, 4))

    decisions = {}
    for name, kind in DECISION_TYPES.items():
        values = []
        for state in _states(2):
            bases = base_index(state.runners)
            if not kind.applies(state.outs, bases):
                values.append(None)
                continue
            try:
                ev = evaluate(name, state, model, table)
            except InsufficientData:
                values.append(None)
                continue
            values.append([round(ev.chosen_probability, 4), round(ev.alternative_probability, 4)])
        decisions[name] = {
            "chosen": kind.chosen,
            "alternative": kind.alternative,
            "byOffense": kind.by_offense,
            "values": values,
        }

    outcomes = {}
    for tactic in (*ESTIMATED, "ibb"):
        outcomes[tactic] = {}
        for outs in range(3):
            for bases in range(8):
                try:
                    rows = table.outcomes(tactic, outs, bases)
                except InsufficientData:
                    continue
                shown = [list(row[:3]) + [round(row[3], 4)] for row in rows if row[3] >= MIN_SHARE]
                outcomes[tactic][f"{outs}{bases}"] = {
                    "n": table.samples(tactic, outs, bases),
                    "rows": shown,
                    "other": round(1.0 - sum(row[3] for row in shown), 4),
                }

    return {
        "maxDiff": MAX_DIFF,
        "innings": len(INNINGS),
        "wp": wp,
        "homeWin": home_win,
        "tie": tie,
        "decisions": decisions,
        "outcomes": outcomes,
        "source": table.source,
        "attribution": ATTRIBUTION,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("demo/index.html"))
    args = parser.parse_args()

    data = build_data(WinProbabilityModel.load_default(), TacticTable.load())
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"{args.out} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
