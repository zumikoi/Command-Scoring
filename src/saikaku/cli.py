"""Command-line entry point for scoring one decision record."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from .decisions import Decision, score_decision
from .model import GameState, WinProbabilityModel
from .report import format_post


def _state(data: dict) -> GameState:
    data = dict(data)
    data["runners"] = tuple(data.get("runners", (False, False, False)))
    return GameState(**data)


def load_decision(path: Path) -> Decision:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Decision(
        team=raw["team"],
        game_id=raw["game_id"],
        decision_type=raw["decision_type"],
        description=raw["description"],
        before=_state(raw["before"]),
        observed_after=_state(raw["observed_after"]),
        best_alternative=raw["best_alternative"],
        alternative_after=_state(raw["alternative_after"]),
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m saikaku.cli samples/decision.json")
    scored = score_decision(load_decision(Path(sys.argv[1])), WinProbabilityModel.load_default())
    print(format_post(scored))
    print(json.dumps(asdict(scored), ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()