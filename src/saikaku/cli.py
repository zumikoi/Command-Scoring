"""Command-line entry point for scoring one decision record."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .decisions import Decision, score_decision
from .model import GameState, WinProbabilityModel
from .report import format_decision
from .tactics import TacticTable


def _state(data: dict) -> GameState:
    data = dict(data)
    data["runners"] = tuple(data.get("runners", (False, False, False)))
    return GameState(**data)


def load_decision(path: Path) -> Decision:
    raw = json.loads(path.read_text(encoding="utf-8"))
    observed = raw.get("observed_after")
    return Decision(
        team=raw["team"],
        game_id=raw["game_id"],
        decision_type=raw["decision_type"],
        description=raw["description"],
        before=_state(raw["before"]),
        observed_after=_state(observed) if observed else None,
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m saikaku.cli samples/decision.json")
    scored = score_decision(
        load_decision(Path(sys.argv[1])), WinProbabilityModel.load_default(), TacticTable.load()
    )
    print(format_decision(scored))


if __name__ == "__main__":
    main()
