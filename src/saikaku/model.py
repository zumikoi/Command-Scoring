"""In-game win probability from the run distribution and NPB game rules.

Every half inning draws its runs from :class:`~saikaku.runs.RunDistribution`,
and the rules decide what happens between half innings: the home team skips
the bottom of the ninth when leading, a walk-off ends the game at once, and an
NPB regular-season game still tied after the twelfth is a draw.

Both teams are treated as league average. Batter, pitcher and venue effects are
deliberately absent until they can be estimated rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path

from .runs import RunDistribution, base_index

#: The fitted distribution ships with the package once it has been built.
DEFAULT_RUN_DISTRIBUTION = Path(__file__).with_name("data") / "run_distribution.json"

#: Score margins beyond this are treated as this; they are decided games.
_MAX_MARGIN = 30


@dataclass(frozen=True)
class GameState:
    """Information available immediately before a decision."""

    inning: int
    half: str
    outs: int
    home_score: int
    away_score: int
    runners: tuple[bool, bool, bool] = (False, False, False)

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


@dataclass(frozen=True)
class GameRules:
    regulation_innings: int = 9
    #: The last inning played before a tie stands. NPB's regular season stops at 12.
    max_innings: int = 12
    #: What a draw is worth. NPB excludes ties from winning percentage, so half.
    tie_value: float = 0.5


NPB_RULES = GameRules()


@dataclass(frozen=True)
class Outcome:
    home_win: float
    tie: float

    @property
    def away_win(self) -> float:
        return 1.0 - self.home_win - self.tie

    def __add__(self, other: "Outcome") -> "Outcome":
        return Outcome(self.home_win + other.home_win, self.tie + other.tie)

    def scaled(self, p: float) -> "Outcome":
        return Outcome(self.home_win * p, self.tie * p)


_HOME_WINS = Outcome(1.0, 0.0)
_AWAY_WINS = Outcome(0.0, 0.0)
_TIE = Outcome(0.0, 1.0)


class WinProbabilityModel:
    """Win probability for the team currently batting."""

    def __init__(self, runs: RunDistribution, rules: GameRules = NPB_RULES) -> None:
        self.runs = runs
        self.rules = rules
        self._start = cache(self._start_of_half)

    @classmethod
    def load_default(cls) -> "WinProbabilityModel":
        if not DEFAULT_RUN_DISTRIBUTION.exists():
            raise FileNotFoundError(
                f"{DEFAULT_RUN_DISTRIBUTION} is missing; build it with python -m saikaku.fit"
            )
        return cls(RunDistribution.load(DEFAULT_RUN_DISTRIBUTION))

    def outcome(self, state: GameState) -> Outcome:
        diff = _clamp(state.run_diff)
        if (
            state.half == "bottom"
            and state.inning >= self.rules.regulation_innings
            and diff > 0
        ):
            return _HOME_WINS
        return self._play_out(
            state.inning, state.half, state.outs, base_index(state.runners), diff
        )

    def probability(self, state: GameState) -> float:
        result = self.outcome(state)
        tie_share = self.rules.tie_value * result.tie
        if state.batting_team_is_home:
            return result.home_win + tie_share
        return result.away_win + tie_share

    def action_value(self, before: GameState, after: GameState) -> float:
        """Return the batting team's win-probability change in percentage points.

        ``after`` may belong to the next half inning; the change is still
        measured for the team that was batting in ``before``.
        """

        after_value = self.probability(after)
        if after.batting_team_is_home != before.batting_team_is_home:
            after_value = 1.0 - after_value
        return (after_value - self.probability(before)) * 100

    def _play_out(self, inning: int, half: str, outs: int, bases: int, diff: int) -> Outcome:
        """Finish the current half inning from a base-out state, then the game."""

        walk_off_possible = half == "bottom" and inning >= self.rules.regulation_innings
        total = Outcome(0.0, 0.0)
        for runs, p in enumerate(self.runs.remaining(outs, bases)):
            if p == 0.0:
                continue
            new_diff = _clamp(diff + runs if half == "bottom" else diff - runs)
            if walk_off_possible and new_diff > 0:
                result = _HOME_WINS
            else:
                result = self._after_half(inning, half, new_diff)
            total = total + result.scaled(p)
        return total

    def _after_half(self, inning: int, half: str, diff: int) -> Outcome:
        rules = self.rules
        if half == "top":
            if inning >= rules.regulation_innings and diff > 0:
                return _HOME_WINS
            return self._start(inning, "bottom", diff)
        if inning >= rules.regulation_innings:
            if diff > 0:
                return _HOME_WINS
            if diff < 0:
                return _AWAY_WINS
            if inning >= rules.max_innings:
                return _TIE
        return self._start(inning + 1, "top", diff)

    def _start_of_half(self, inning: int, half: str, diff: int) -> Outcome:
        return self._play_out(inning, half, 0, 0, diff)


def _clamp(diff: int) -> int:
    return max(-_MAX_MARGIN, min(_MAX_MARGIN, diff))
