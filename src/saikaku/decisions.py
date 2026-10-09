"""Decision records and their scores.

A record holds the state the manager faced and the call that was made. The
score comes from :func:`saikaku.tactics.evaluate` and ignores what happened
next; the result, when recorded, is reported beside it for contrast only.
"""

from __future__ import annotations

from dataclasses import dataclass

from .events import EventTable
from .model import GameState, WinProbabilityModel
from .tactics import DECISION_TYPES, Evaluation, Matchup, TacticTable, evaluate

#: Differences smaller than this are shown as even. It is a display rounding,
#: not a statistical threshold.
EVEN_MARGIN = 0.5


@dataclass(frozen=True)
class Decision:
    team: str
    game_id: str
    decision_type: str
    description: str
    before: GameState
    #: The state right after the play, if it was recorded. Not used to score.
    observed_after: GameState | None = None
    matchup: Matchup = Matchup()


@dataclass(frozen=True)
class ScoredDecision:
    decision: Decision
    evaluation: Evaluation
    #: What the actual result did to the deciding team's win probability, in points.
    result_change: float | None

    @property
    def verdict(self) -> str:
        value = self.evaluation.value
        if abs(value) < EVEN_MARGIN:
            return "互角"
        return "有利" if value > 0 else "不利"


def score_decision(
    decision: Decision, model: WinProbabilityModel, table: TacticTable, events: EventTable
) -> ScoredDecision:
    evaluation = evaluate(
        decision.decision_type, decision.before, model, table, events, decision.matchup
    )
    result_change = None
    if decision.observed_after is not None:
        change = model.action_value(decision.before, decision.observed_after)
        by_offense = DECISION_TYPES[decision.decision_type].by_offense
        result_change = change if by_offense else -change
    return ScoredDecision(decision, evaluation, result_change)
