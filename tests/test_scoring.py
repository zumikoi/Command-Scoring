from saikaku.decisions import Decision, score_decision
from saikaku.model import GameState, WinProbabilityModel


def state(**changes):
    values = dict(
        inning=7,
        half="top",
        outs=0,
        home_score=3,
        away_score=3,
        runners=(True, False, False),
        batter_quality=0.4,
        pitcher_quality=0.2,
    )
    values.update(changes)
    return GameState(**values)


def test_scoring_compares_observed_action_with_alternative():
    before = state()
    observed = state(outs=1, runners=(False, True, False))
    alternative = state()
    decision = Decision(
        team="中日",
        game_id="test",
        decision_type="送りバント",
        description="無死一塁",
        before=before,
        observed_after=observed,
        best_alternative="通常打撃",
        alternative_after=alternative,
    )

    result = score_decision(decision, WinProbabilityModel())

    assert result.decision_cost < 0
    assert result.grade == "D"
