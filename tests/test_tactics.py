from collections import Counter

import pytest

from saikaku.decisions import Decision, score_decision
from saikaku.model import GameState
from saikaku.retrosheet import Play
from saikaku.runs import Transition
from saikaku.tactics import (
    MIN_SAMPLES,
    InsufficientData,
    TacticTable,
    classify,
    evaluate,
    intentional_walk,
)

TIED_SEVENTH = dict(inning=7, half="top", home_score=3, away_score=3)


def state(outs=0, runners=(True, False, False), **changes):
    return GameState(outs=outs, runners=runners, **{**TIED_SEVENTH, **changes})


def table_with(**rows) -> TacticTable:
    """Build a table from {tactic: {(outs, bases): {(o, b, r): n}}}."""

    counts = {name: {} for name in ("swing", "bunt", "steal2", "steal3")}
    for tactic, by_state in rows.items():
        counts[tactic] = {s: Counter(c) for s, c in by_state.items()}
    return TacticTable(counts)


@pytest.mark.parametrize(
    "play, expected",
    [
        (Play(Transition(0, 1, 1, 2, 0), plate_appearance=True, bunt_attempt=True), "bunt"),
        (Play(Transition(0, 1, 0, 3, 0), plate_appearance=True), "swing"),
        (Play(Transition(0, 1, 0, 3, 0), plate_appearance=True, intentional_walk=True), None),
        (Play(Transition(0, 1, 0, 2, 0), steal_target=2), "steal2"),
        (Play(Transition(0, 2, 0, 4, 0), steal_target=3), "steal3"),
        (Play(Transition(0, 1, 0, 2, 0)), None),
    ],
)
def test_classify(play, expected):
    assert classify(play) == expected


@pytest.mark.parametrize(
    "bases, expected_bases, runs",
    [
        (0b000, 0b001, 0),
        (0b001, 0b011, 0),
        (0b010, 0b011, 0),
        (0b100, 0b101, 0),
        (0b011, 0b111, 0),
        (0b111, 0b111, 1),
    ],
)
def test_intentional_walk_moves_only_forced_runners(bases, expected_bases, runs):
    assert intentional_walk(1, bases) == (1, expected_bases, runs, 1.0)


def test_sparse_states_are_not_estimated():
    table = table_with(bunt={(0, 1): {(1, 2, 0): MIN_SAMPLES - 1}})

    with pytest.raises(InsufficientData):
        table.outcomes("bunt", 0, 1)


def test_a_bunt_that_always_succeeds_is_scored_against_swinging(model):
    table = table_with(
        bunt={(0, 1): {(1, 2, 0): 100}},
        swing={(0, 1): {(1, 1, 0): 70, (0, 3, 0): 30}},
    )

    result = evaluate("送りバント", state(), model, table)

    expected_bunt = model.probability(state(outs=1, runners=(False, True, False)))
    assert result.chosen_probability == pytest.approx(expected_bunt)
    assert result.chosen_samples == 100
    assert result.alternative_samples == 100


def test_a_certain_steal_beats_staying_put(model):
    table = table_with(steal2={(0, 1): {(0, 2, 0): 100}})

    result = evaluate("二盗", state(), model, table)

    assert result.alternative == "stay"
    assert result.value > 0


def test_intentional_walk_is_scored_for_the_fielding_team(model):
    # Swinging away always ends in an out, so walking the batter can only hurt.
    table = table_with(swing={(1, 2): {(2, 2, 0): 100}})

    result = evaluate("敬遠", state(outs=1, runners=(False, True, False)), model, table)

    assert result.value < 0


def test_impossible_calls_are_rejected(model):
    with pytest.raises(ValueError):
        evaluate("送りバント", state(runners=(False, False, False)), model, table_with())
    with pytest.raises(ValueError):
        evaluate("二盗", state(runners=(True, True, False)), model, table_with())


def test_unsupported_calls_say_why(model):
    with pytest.raises(InsufficientData, match="継投"):
        evaluate("継投", state(), model, table_with())


def test_result_is_reported_but_not_scored(model):
    table = table_with(
        bunt={(0, 1): {(1, 2, 0): 100}},
        swing={(0, 1): {(1, 1, 0): 70, (0, 3, 0): 30}},
    )
    good = Decision("中日", "g", "送りバント", "", state(), state(outs=1, runners=(False, True, False)))
    bad = Decision("中日", "g", "送りバント", "", state(), state(outs=2, runners=(False,) * 3))

    good_score = score_decision(good, model, table)
    bad_score = score_decision(bad, model, table)

    assert good_score.evaluation == bad_score.evaluation
    assert good_score.result_change > bad_score.result_change


def test_json_round_trip():
    table = table_with(bunt={(0, 1): {(1, 2, 0): 3, (2, 0, 0): 1}})

    restored = TacticTable.from_json(table.to_json())

    assert restored.counts["bunt"] == table.counts["bunt"]
