from __future__ import annotations

from pathlib import Path

import pytest

from phoenix_aero_lite.solver.su2_history import (
    HistoryParseError,
    history_is_complete,
    parse_history_csv,
)


HEADER = '"Inner_Iter","rms[P]","rms[k]","rms[w]","CD","CL","CFx","CFy","CFz"\n'


def test_parses_official_columns_duplicate_header_and_ignores_partial_tail(
    tmp_path: Path,
):
    path = tmp_path / "history.csv"
    path.write_text(
        HEADER
        + "0,-2,-3,-4,0.1,0.2,1,2,3\n"
        + HEADER
        + "1,-3,-4,-5,0.09,0.21,1.1,2.1,3.1\n"
        + "2,-4",
        encoding="utf-8",
        newline="",
    )
    history = parse_history_csv(path)
    assert len(history.samples) == 2
    assert history_is_complete(path) is False
    assert history.samples[-1].iteration == 1
    assert history.samples[-1].cl == pytest.approx(0.21)
    assert history.source_path == path.resolve()


def test_rejects_missing_columns_nonfinite_and_finished_partial_row(tmp_path: Path):
    missing = tmp_path / "missing.csv"
    missing.write_text('"Inner_Iter","rms[P]"\n0,-2\n', encoding="utf-8")
    with pytest.raises(HistoryParseError, match="HISTORY_COLUMNS_MISSING"):
        parse_history_csv(missing)

    nonfinite = tmp_path / "nonfinite.csv"
    nonfinite.write_text(HEADER + "0,nan,-3,-4,0.1,0.2,1,2,3\n", encoding="utf-8")
    with pytest.raises(HistoryParseError, match="HISTORY_NONFINITE"):
        parse_history_csv(nonfinite)

    partial = tmp_path / "partial.csv"
    partial.write_text(HEADER + "0,-2,-3\n", encoding="utf-8")
    with pytest.raises(HistoryParseError, match="HISTORY_ROW_INVALID"):
        parse_history_csv(partial)


def test_replays_official_sst_history():
    official = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "su2"
        / "official_inc_rans_sst_history.csv"
    )
    history = parse_history_csv(official)
    assert len(history.samples) > 10
    assert history.samples[0].iteration == 0


def test_accepts_complete_last_row_without_trailing_newline(tmp_path: Path):
    path = tmp_path / "history.csv"
    path.write_text(
        HEADER + "0,-2,-3,-4,0.1,0.2,1,2,3",
        encoding="utf-8",
        newline="",
    )
    assert len(parse_history_csv(path).samples) == 1
    assert history_is_complete(path) is True


def test_accepts_official_su2_padded_quoted_header(tmp_path: Path):
    path = tmp_path / "history.csv"
    path.write_text(
        '"Inner_Iter",     "rms[P]"     ,     "rms[k]"     ,'
        '     "rms[w]"     , "CD" , "CL" , "CFx" , "CFy" , "CFz"   \r\n'
        "0,-2,-3,-4,0.1,0.2,1,2,3\r\n",
        encoding="utf-8",
        newline="",
    )
    history = parse_history_csv(path)
    assert history.samples[0].cl == pytest.approx(0.2)
