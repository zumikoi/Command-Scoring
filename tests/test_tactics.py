from collections import Counter

import pytest

from saikaku.abilities import AVERAGE, EVENTS, Ability
from saikaku.decisions import Decision, score_decision
from saikaku.model import GameState
from saikaku.retrosheet import Play
from saikaku.runs import Transition
from saikaku.tactics import (
    MIN_SAMPLES,
    InsufficientData,
    Matchup,
    TacticTable,
    classify,
    evaluate,
    intentional_walk,
)

TIED_SEVENTH = dict(inning=7, half="top", home_score=3, away_score=3)
SLUGGER = Ability({**{e: 1.0 for e in EVENTS}, "HR": 3.0, "BB": 1.5, "K": 0.8}, "slugger")
WEAK = Ability({**{e: 1.0 for e in EVENTS}, "HR": 0.2, "1B": 0.6, "2B": 0.5, "BB": 0.5, "K": 1.6}, "weak")
ACE = Ability({**{e: 1.0 for e in EVENTS}, "K": 1.6, "BB": 0.6, "HR": 0.5}, "ace")


def state(outs=0, runners=(True, False, False), **changes):
    return GameState(outs=outs, runners=runners, **{**TIED_SEVENTH, **changes})


def table_with(**rows) -> TacticTable:
    """Build a table from {tactic: {(outs, bases): {(o, b, r): n}}}."""

    counts = {name: {} for name in ("bunt", "steal2", "steal3")}
    for tactic, by_state in rows.items():
        counts[tactic] = {s: Counter(c) for s, c in by_state.items()}
    return TacticTable(counts)


SURE_BUNT = table_with(bunt={(0, 1): {(1, 2, 0): 100}, (0, 3): {(1, 6, 0): 100}})


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


def test_matchup_pads_the_order_with_average_batters():
    assert Matchup(lineup=(SLUGGER,)).batters() == (SLUGGER, AVERAGE, AVERAGE)
    assert Matchup(lineup=(SLUGGER,)).batters(1) == (AVERAGE, AVERAGE)


def test_bunting_looks_better_in_front_of_a_weak_batter(model, events):
    weak = evaluate("送りバント", state(), model, SURE_BUNT, events, Matchup((WEAK,)))
    strong = evaluate("送りバント", state(), model, SURE_BUNT, events, Matchup((SLUGGER,)))

    assert weak.value > strong.value


def test_bunting_looks_worse_against_a_weak_pitcher_than_an_ace(model, events):
    ace = evaluate("送りバント", state(), model, SURE_BUNT, events, Matchup(pitcher=ACE))
    average = evaluate("送りバント", state(), model, SURE_BUNT, events, Matchup())

    assert ace.value > average.value


def test_a_certain_steal_beats_staying_put(model, events):
    table = table_with(steal2={(0, 1): {(0, 2, 0): 100}})

    result = evaluate("二盗", state(), model, table, events)

    assert result.alternative == "stay"
    assert result.value > 0


def test_walking_the_slugger_to_face_a_weak_hitter_pays(model, events):
    second = state(outs=1, runners=(False, True, False))
    walk_slugger = evaluate("敬遠", second, model, table_with(), events, Matchup((SLUGGER, WEAK)))
    walk_weak = evaluate("敬遠", second, model, table_with(), events, Matchup((WEAK, SLUGGER)))

    assert walk_slugger.value > walk_weak.value
    assert walk_weak.value < 0


def test_pinch_hitting_a_better_batter_helps(model, events):
    result = evaluate(
        "代打", state(), model, table_with(), events, Matchup((WEAK,), pinch_hitter=SLUGGER)
    )

    assert result.value > 0


def test_bringing_in_an_ace_helps_the_fielding_team(model, events):
    result = evaluate("継投", state(), model, table_with(), events, Matchup(reliever=ACE))

    assert result.value > 0


def test_substitutions_need_the_new_player(model, events):
    with pytest.raises(ValueError, match="代打"):
        evaluate("代打", state(), model, table_with(), events)
    with pytest.raises(ValueError, match="継投"):
        evaluate("継投", state(), model, table_with(), events)


def test_impossible_calls_are_rejected(model, events):
    with pytest.raises(ValueError):
        evaluate("送りバント", state(runners=(False, False, False)), model, table_with(), events)
    with pytest.raises(ValueError):
        evaluate("二盗", state(runners=(True, True, False)), model, table_with(), events)


def test_result_is_reported_but_not_scored(model, events):
    good = Decision("中日", "g", "送りバント", "", state(), state(outs=1, runners=(False, True, False)))
    bad = Decision("中日", "g", "送りバント", "", state(), state(outs=2, runners=(False,) * 3))

    good_score = score_decision(good, model, SURE_BUNT, events)
    bad_score = score_decision(bad, model, SURE_BUNT, events)

    assert good_score.evaluation == bad_score.evaluation
    assert good_score.result_change > bad_score.result_change


def test_json_round_trip():
    table = table_with(bunt={(0, 1): {(1, 2, 0): 3, (2, 0, 0): 1}})

    restored = TacticTable.from_json(table.to_json())

    assert restored.counts["bunt"] == table.counts["bunt"]
