"""Command-line entry point for scoring one decision record.

Players are optional. Each may be a profile name such as ``"強打者（上位10%）"``
or a stat line typed in by hand, keyed in Japanese::

    "打者": {"打席": 520, "安打": 140, "二塁打": 25, "三塁打": 2, "本塁打": 24,
             "四球": 60, "死球": 5, "三振": 110},
    "次の打者": ["非力（下位10%）", "平均的なレギュラー"],
    "投手": {"打者": 600, "被安打": 130, "被本塁打": 12, "与四球": 40, "奪三振": 150},
    "代打": ..., "継投": ...,
    "リーグ": {league batting totals, same keys as a batter}

Stat lines are compared with ``"リーグ"`` when given, otherwise with the MLB
league the model was fitted on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Mapping

from .abilities import (
    BATTER_KEYS,
    PITCHER_KEYS,
    Ability,
    StatLine,
    batter_ability,
    league_rates,
    pitcher_ability,
)
from .decisions import Decision, score_decision
from .events import EventTable
from .model import GameState, WinProbabilityModel
from .report import format_decision
from .tactics import Matchup, TacticTable


def _state(data: dict) -> GameState:
    data = dict(data)
    data["runners"] = tuple(data.get("runners", (False, False, False)))
    return GameState(**data)


def parse_ability(
    raw: object, batting: bool, events: EventTable, league: Mapping[str, float]
) -> Ability:
    if isinstance(raw, str):
        return events.profile(raw, batting)
    if isinstance(raw, Mapping):
        if batting:
            return batter_ability(StatLine.from_mapping(raw, BATTER_KEYS), league)
        return pitcher_ability(StatLine.from_mapping(raw, PITCHER_KEYS), league)
    raise ValueError(f"player must be a profile name or a stat line, got {raw!r}")


def parse_matchup(raw: Mapping, events: EventTable) -> Matchup:
    league = events.league
    if raw.get("リーグ"):
        league = league_rates(StatLine.from_mapping(raw["リーグ"], BATTER_KEYS))

    def player(key: str, batting: bool) -> Ability | None:
        value = raw.get(key)
        return None if value is None else parse_ability(value, batting, events, league)

    lineup = []
    if raw.get("打者") is not None:
        lineup.append(player("打者", True))
        lineup.extend(parse_ability(v, True, events, league) for v in raw.get("次の打者", []))
    pitcher = player("投手", False)
    return Matchup(
        lineup=tuple(lineup),
        pitcher=pitcher if pitcher is not None else Matchup().pitcher,
        pinch_hitter=player("代打", True),
        reliever=player("継投", False),
    )


def load_decision(path: Path, events: EventTable) -> Decision:
    raw = json.loads(path.read_text(encoding="utf-8"))
    observed = raw.get("observed_after")
    return Decision(
        team=raw["team"],
        game_id=raw["game_id"],
        decision_type=raw["decision_type"],
        description=raw["description"],
        before=_state(raw["before"]),
        observed_after=_state(observed) if observed else None,
        matchup=parse_matchup(raw, events),
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m saikaku.cli samples/decision.json")
    events = EventTable.load()
    scored = score_decision(
        load_decision(Path(sys.argv[1]), events),
        WinProbabilityModel.load_default(),
        TacticTable.load(),
        events,
    )
    print(format_decision(scored))


if __name__ == "__main__":
    main()
