"""A transparent baseline model for in-game win probability.

The model is deliberately small and inspectable. It is a starting point for
replacing the coefficients with estimates learned from historical game data.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import exp


@dataclass(frozen=True)
class GameState:
    """Information available immediately before a decision."""

    inning: int
    half: str
    outs: int
    home_score: int
    away_score: int
    runners: tuple[bool, bool, bool] = (False, False, False)
    batter_quality: float = 0.0
    pitcher_quality: float = 0.0

    def __post_init__(self) -> None:
        if self.inning < 1:
            raise ValueError("inning must be at least 1")
        if self.half not in {"top", "bottom"}:
            raise ValueError("half must be 'top' or 'bottom'")
        if self.outs not in {0, 1, 2, 3}:
            raise ValueError("outs must be 0, 1, 2, or 3")
        if self.home_score < 0 or self.away_score < 0:
            raise ValueError("scores must not be negative")
        if len(self.runners) != 3 or not all(isinstance(runner, bool) for runner in self.runners):
            raise ValueError("runners must contain three boolean base flags")

    @property
    def run_diff(self) -> int:
        return self.home_score - self.away_score

    @property
    def batting_team_is_home(self) -> bool:
        return self.half == "bottom"

    @property
    def batting_team_run_diff(self) -> int:
        return self.run_diff if self.batting_team_is_home else -self.run_diff

    def with_scores(self, batting_team_runs: int) -> "GameState":
        if self.batting_team_is_home:
            return replace(self, home_score=self.home_score + batting_team_runs)
        return replace(self, away_score=self.away_score + batting_team_runs)

    @property
    def half_inning_is_over(self) -> bool:
        """True once the third out is recorded, when no one is batting."""

        return self.outs == 3

    def next_half_inning(self) -> "GameState":
        """Return the state starting the next half inning.

        The batting team changes, so a probability computed for the returned
        state belongs to the opponent of the team that was batting here.
        """

        if self.half == "top":
            return replace(self, half="bottom", outs=0, runners=(False, False, False))
        return replace(
            self,
            inning=self.inning + 1,
            half="top",
            outs=0,
            runners=(False, False, False),
        )


class WinProbabilityModel:
    """Estimate win probability for the team currently batting.

    This is a baseline, not a claim about the true probabilities. Production
    use should fit the parameters by season, venue, league, and game state.
    """

    def probability(self, state: GameState) -> float:
        if state.half_inning_is_over:
            # Nobody is batting on the third out. The state is worth exactly the
            # complement of the opponent's position leading off the next half.
            return 1.0 - self.probability(state.next_half_inning())
        innings_remaining = max(0.25, 9.5 - state.inning)
        score_term = 0.42 * state.batting_team_run_diff
        inning_term = 0.08 * (state.inning - 5)
        batter_term = 0.18 * state.batter_quality
        pitcher_term = -0.18 * state.pitcher_quality
        base_term = 0.23 * sum(state.runners)
        out_term = -0.31 * state.outs
        late_term = 0.22 if state.batting_team_is_home and state.inning >= 9 else 0.0
        linear = (score_term + inning_term + batter_term + pitcher_term +
                  base_term + out_term + late_term) / innings_remaining
        return 1.0 / (1.0 + exp(-linear))

    def action_value(self, before: GameState, after: GameState) -> float:
        """Return win-probability change in percentage points."""

        return (self.probability(after) - self.probability(before)) * 100
