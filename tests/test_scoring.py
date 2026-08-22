from saikaku.decisions import Decision, score_decision
from saikaku.model import GameState, WinProbabilityModel
import pytest


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


@pytest.mark.parametrize(
    "changes",
    [
        {"inning": 0},
        {"half": "middle"},
        {"outs": 4},
        {"outs": -1},
        {"home_score": -1},
        {"runners": (True, False)},
    ],
)
def test_game_state_rejects_invalid_input(changes):
    with pytest.raises(ValueError):
        state(**changes)


def test_game_state_accepts_valid_boundary_values():
    valid = state(inning=1, outs=2, home_score=0, away_score=0)

    assert valid.inning == 1
    assert valid.outs == 2


def test_third_out_is_a_valid_state_because_source_data_records_it():
    ended = state(outs=3)

    assert ended.half_inning_is_over
    assert not state(outs=2).half_inning_is_over


def test_next_half_inning_hands_the_bat_to_the_other_team():
    after_top = state(inning=7, half="top", outs=3).next_half_inning()

    assert (after_top.inning, after_top.half) == (7, "bottom")
    assert after_top.outs == 0
    assert after_top.runners == (False, False, False)

    after_bottom = state(inning=7, half="bottom", outs=3).next_half_inning()

    assert (after_bottom.inning, after_bottom.half) == (8, "top")


def test_third_out_is_valued_as_the_complement_of_the_opponents_position():
    model = WinProbabilityModel()
    ended = state(inning=7, half="top", outs=3)

    assert model.probability(ended) == pytest.approx(
        1.0 - model.probability(ended.next_half_inning())
    )
