from math import comb

import pytest

from saikaku.runs import RunDistribution, Transition, TransitionTable, base_index, state_key


def test_base_index_puts_first_base_in_the_low_bit():
    assert base_index((True, False, False)) == 1
    assert base_index((False, False, True)) == 4
    assert state_key(2, base_index((True, False, True))) == "2-101"


def test_home_runs_and_outs_only_give_a_negative_binomial():
    # With only outs (p) and bases-empty home runs (q), the runs before the
    # third out follow C(r + 2, 2) p^3 q^r.
    p, q = 0.75, 0.25
    table = TransitionTable()
    for outs in range(3):
        for bases in range(8):
            table.add(Transition(outs, bases, outs + 1, bases, 0))
            table.add(Transition(outs, bases, outs + 1, bases, 0))
            table.add(Transition(outs, bases, outs + 1, bases, 0))
            table.add(Transition(outs, bases, outs, 0, bin(bases).count("1") + 1))

    runs = RunDistribution.from_table(table, max_runs=40)

    for r in range(6):
        assert runs.remaining(0, 0)[r] == pytest.approx(comb(r + 2, 2) * p**3 * q**r)


def test_distributions_are_proper_and_ordered(runs):
    for outs in range(3):
        for bases in range(8):
            assert sum(runs.remaining(outs, bases)) == pytest.approx(1.0)
    assert runs.expected_runs(0, 0) > runs.expected_runs(1, 0) > runs.expected_runs(2, 0)
    assert runs.expected_runs(0, 7) > runs.expected_runs(0, 1) > runs.expected_runs(0, 0)


def test_third_out_leaves_no_runs(runs):
    assert runs.remaining(3, 0)[0] == 1.0


def test_self_loops_are_ignored():
    table = TransitionTable()
    table.add(Transition(1, 1, 1, 1, 0))

    assert table.total() == 0


def test_runners_are_cleared_on_the_third_out():
    table = TransitionTable()
    table.add(Transition(2, 7, 3, 7, 0))

    assert table.counts[(2, 7)] == {(3, 0, 0): 1}


def test_unobserved_state_is_an_error():
    with pytest.raises(ValueError, match="0-000"):
        RunDistribution.from_table(TransitionTable())


@pytest.mark.parametrize(
    "args",
    [(3, 0, 3, 0, 0), (1, 0, 0, 0, 0), (0, 8, 1, 0, 0), (0, 0, 1, 0, -1)],
)
def test_transition_rejects_impossible_moves(args):
    with pytest.raises(ValueError):
        Transition(*args)


def test_json_round_trip(runs):
    restored = RunDistribution.from_json(runs.to_json())

    assert restored.by_state == runs.by_state
    assert restored.max_runs == runs.max_runs
