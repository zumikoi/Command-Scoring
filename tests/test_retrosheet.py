import zipfile

import pytest

from saikaku.retrosheet import SchemaError, read_transitions
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


def test_missing_column_is_an_error(tmp_path):
    path = write_csv(tmp_path / "bad.csv", header=HEADER.replace(",runs", ",rbi"))

    with pytest.raises(SchemaError, match="runs"):
        list(read_transitions(path))
