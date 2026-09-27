import pytest

from saikaku.decisions import Decision, score_decision
from saikaku.model import GameState


def state(**changes):
    values = dict(
        inning=7,
        half="top",
        outs=0,
        home_score=3,
        away_score=3,
        runners=(True, False, False),
    )
    values.update(changes)
    return GameState(**values)


def test_scoring_compares_observed_action_with_alternative(model):
    before = state()
    decision = Decision(
        team="中日",
        game_id="test",
        decision_type="送りバント",
        description="無死一塁",
        before=before,
        observed_after=state(outs=1, runners=(False, True, False)),
        best_alternative="通常打撃",
        alternative_after=before,
    )

    result = score_decision(decision, model)

    assert result.alternative_change == 0.0
    assert result.decision_cost == pytest.approx(result.observed_change)


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


def test_next_half_inning_hands_the_bat_to_the_other_team():
    after_top = state(inning=7, half="top", outs=3).next_half_inning()

    assert (after_top.inning, after_top.half) == (7, "bottom")
    assert after_top.outs == 0
    assert after_top.runners == (False, False, False)

    after_bottom = state(inning=7, half="bottom", outs=3).next_half_inning()

    assert (after_bottom.inning, after_bottom.half) == (8, "top")


def test_third_out_is_valued_as_the_complement_of_the_opponents_position(model):
    ended = state(inning=7, half="top", outs=3)

    assert model.probability(ended) == pytest.approx(
        1.0 - model.probability(ended.next_half_inning())
    )


def test_action_value_follows_the_batting_team_across_the_half(model):
    before = state(outs=2, runners=(False, False, False))
    ended = state(outs=3, runners=(False, False, False))

    assert model.action_value(before, ended) == pytest.approx(
        model.action_value(before, ended.next_half_inning())
    )


@pytest.mark.parametrize(
    "fewer, more",
    [
        # A third out never helps the batting team.
        ({"outs": 3}, {"outs": 2}),
        ({"outs": 2}, {"outs": 1}),
        ({"runners": (False, False, False)}, {"runners": (True, False, False)}),
        ({"away_score": 3}, {"away_score": 4}),
    ],
)
def test_probability_moves_the_right_way(model, fewer, more):
    assert model.probability(state(**fewer)) < model.probability(state(**more))


def test_outcomes_are_a_probability_split(model):
    result = model.outcome(state(inning=1, half="top", outs=0, home_score=0, away_score=0))

    assert 0 < result.home_win < 1
    assert 0 < result.tie < 1
    assert result.home_win + result.tie + result.away_win == pytest.approx(1.0)


def test_home_team_skips_the_bottom_of_the_ninth_when_leading(model):
    over = state(inning=9, half="top", outs=3, home_score=2, away_score=1)

    assert model.outcome(over).home_win == 1.0


def test_leading_home_team_in_the_bottom_of_the_ninth_has_already_won(model):
    walked_off = state(inning=10, half="bottom", outs=1, home_score=4, away_score=3)

    assert model.outcome(walked_off).home_win == 1.0


def test_tie_after_the_twelfth_stands(model):
    over = state(inning=12, half="bottom", outs=3, home_score=2, away_score=2)

    assert model.outcome(over).tie == 1.0


def test_extra_innings_carry_a_real_chance_of_a_draw(model):
    early = model.outcome(state(inning=10, half="top", outs=0, runners=(False,) * 3))
    late = model.outcome(state(inning=12, half="top", outs=0, runners=(False,) * 3))

    assert late.tie > early.tie > 0


def test_walk_off_threat_raises_home_chances(model):
    loaded = state(inning=9, half="bottom", outs=0, runners=(True, True, True))
    empty = state(inning=9, half="bottom", outs=2, runners=(False, False, False))

    assert model.probability(loaded) > model.probability(empty)
