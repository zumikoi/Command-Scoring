"""Build the data files the models ship with.

    python -m saikaku.fit <plays.zip> [<plays.zip> ...]

Writes ``src/saikaku/data/run_distribution.json`` and ``tactics.json`` and
prints the run expectancy table so the fit can be checked by eye.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .model import DEFAULT_RUN_DISTRIBUTION
from .retrosheet import ATTRIBUTION, read_all
from .runs import RunDistribution, TransitionTable
from .tactics import DEFAULT_TACTICS, TacticTable


def run_expectancy_table(runs: RunDistribution) -> str:
    lines = ["走者    0死    1死    2死"]
    for mask in ("000", "100", "010", "001", "110", "101", "011", "111"):
        bases = sum(1 << i for i, char in enumerate(mask) if char == "1")
        values = "  ".join(f"{runs.expected_runs(outs, bases):5.3f}" for outs in range(3))
        lines.append(f"{mask}  {values}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_RUN_DISTRIBUTION.parent)
    args = parser.parse_args()

    plays = list(read_all(args.paths))
    table = TransitionTable.from_transitions(play.transition for play in plays)
    names = ", ".join(path.name for path in args.paths)
    source = f"Retrosheet {names} ({table.total()} transitions). {ATTRIBUTION}"
    runs = RunDistribution.from_table(table, source=source)
    tactics = TacticTable.from_plays(plays, source=source)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / DEFAULT_RUN_DISTRIBUTION.name).write_text(runs.to_json(), encoding="utf-8")
    (args.out_dir / DEFAULT_TACTICS.name).write_text(tactics.to_json(), encoding="utf-8")
    print(f"{table.total()} transitions -> {args.out_dir}")
    for tactic, by_state in tactics.counts.items():
        print(f"  {tactic}: {sum(sum(c.values()) for c in by_state.values())} plays")
    print(run_expectancy_table(runs))


if __name__ == "__main__":
    main()
