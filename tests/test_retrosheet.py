import zipfile

import pytest

from saikaku.retrosheet import SchemaError, read_plays, read_transitions
from saikaku.runs import Transition

HEADER = "gid,inning,top_bot,outs_pre,outs_post,br1_pre,br2_pre,br3_pre,br1_post,br2_post,br3_post,runs"
ROWS = [
    # Single with nobody on.
    "ANA202404010,1,0,0,0,,,,smitj001,,,0",
    # Two-run homer with runners on first and third.
    "ANA202404010,1,0,0,0,smitj001,,jonef001,,,,2",
    # Inning-ending double play: runners on the post columns are irrelevant.
    "ANA202404010,1,0,1,3,smitj001,,,smitj001,,,0",
]


def write_csv(path, rows=ROWS, header=HEADER):
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_reads_base_out_transitions(tmp_path):
    transitions = list(read_transitions(write_csv(tmp_path / "2024plays.csv")))

    assert transitions == [
        Transition(0, 0, 0, 1, 0),
        Transition(0, 0b101, 0, 0, 2),
        Transition(1, 1, 3, 1, 0),
    ]


def test_reads_every_csv_inside_a_zip(tmp_path):
    csv_path = write_csv(tmp_path / "2024plays.csv")
    zip_path = tmp_path / "2024plays.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(csv_path, "2024plays.csv")

    assert len(list(read_transitions(zip_path))) == 3


def test_only_regular_season_games_are_read(tmp_path):
    header = HEADER + ",gametype"
    rows = [ROWS[0] + ",regular", ROWS[1] + ",worldseries"]
    path = write_csv(tmp_path / "2024plays.csv", rows=rows, header=header)

    assert list(read_transitions(path)) == [Transition(0, 0, 0, 1, 0)]


def test_missing_column_is_an_error(tmp_path):
    path = write_csv(tmp_path / "bad.csv", header=HEADER.replace(",runs", ",rbi"))

    with pytest.raises(SchemaError, match="runs"):
        list(read_transitions(path))


def test_reads_tactic_flags(tmp_path):
    header = HEADER + ",pa,bunt,k,pitches,iw,sb2,cs2,sb3,cs3"
    rows = [
        # Sacrifice bunt, and a strikeout on a foul bunt.
        "G,1,0,0,1,a,,,,b,,0,1,1,0,BX,0,0,0,0,0",
        "G,1,0,0,1,a,,,a,,,0,1,0,1,CFL,0,0,0,0,0",
        # Steal of second between pitches, and a strikeout with a steal.
        "G,1,0,0,0,a,,,,a,,0,0,0,0,,0,1,0,0,0",
        "G,1,0,0,1,a,,,,a,,0,1,0,1,CCS,0,1,0,0,0",
        # Double steal: not a single decision to run.
        "G,1,0,0,0,a,b,,,a,b,0,0,0,0,,0,1,0,1,0",
    ]
    plays = list(read_plays(write_csv(tmp_path / "p.csv", rows=rows, header=header)))

    assert [p.bunt_attempt for p in plays] == [True, True, False, False, False]
    assert [p.steal_target for p in plays] == [None, None, 2, None, None]
