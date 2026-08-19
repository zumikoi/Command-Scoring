"""Decision records and counterfactual scoring."""

from __future__ import annotations

from dataclasses import dataclass

from .model import GameState, WinProbabilityModel


@dataclass(frozen=True)
class Decision:
    team: str
    game_id: str
    decision_type: str
    description: str
    before: GameState
    observed_after: GameState
    best_alternative: str
    alternative_after: GameState


@dataclass(frozen=True)
class ScoredDecision:
    decision: Decision
    observed_change: float
    alternative_change: float
    decision_cost: float

    @property
    def grade(self) -> str:
        if self.decision_cost >= 1.5:
            return "A"
        if self.decision_cost >= 0.0:
            return "B"
        if self.decision_cost >= -1.5:
            return "C"
        return "D"


def score_decision(decision: Decision, model: WinProbabilityModel) -> ScoredDecision:
    observed = model.action_value(decision.before, decision.observed_after)
    alternative = model.action_value(decision.before, decision.alternative_after)
    return ScoredDecision(decision, observed, alternative, observed - alternative)
