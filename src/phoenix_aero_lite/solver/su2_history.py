"""Parse official SU2 CSV history output into immutable typed samples."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
import math
from pathlib import Path

import pandas as pd


class HistoryParseError(ValueError):
    """Stable history parsing failure."""


@dataclass(frozen=True, slots=True)
class HistorySample:
    """One validated SU2 inner iteration."""

    iteration: int
    rms_pressure: float
    rms_tke: float
    rms_omega: float
    cd: float | None
    cl: float | None
    force_x: float | None
    force_y: float | None
    force_z: float | None


@dataclass(frozen=True, slots=True)
class Su2History:
    """Immutable sequence suitable for convergence decisions and reporting."""

    source_path: Path | None
    samples: tuple[HistorySample, ...]


_REQUIRED = ("Inner_Iter", "rms[P]", "rms[k]", "rms[w]")
_OPTIONAL = ("CD", "CL", "CFx", "CFy", "CFz")


def history_is_complete(path: Path) -> bool:
    """Return whether the final CSV record has the same shape as its header."""

    if not isinstance(path, Path) or not path.is_file():
        return False
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    try:
        header = next(csv.reader([lines[0]]))
        final = next(csv.reader([lines[-1]]))
    except (csv.Error, StopIteration):
        return False
    return bool(header) and len(final) == len(header) and final[0].strip() != header[0].strip()


def parse_history_csv(path: Path) -> Su2History:
    """Read an SU2 CSV, ignoring only an actively written incomplete tail."""

    if not isinstance(path, Path) or not path.is_file():
        raise HistoryParseError("HISTORY_MISSING")
    resolved = path.resolve(strict=True)
    raw = resolved.read_bytes()
    if not raw:
        raise HistoryParseError("HISTORY_EMPTY")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HistoryParseError("HISTORY_ENCODING_INVALID") from None
    if not text.endswith(("\n", "\r")):
        last_break = max(text.rfind("\n"), text.rfind("\r"))
        if last_break < 0:
            raise HistoryParseError("HISTORY_EMPTY")
        header = next(csv.reader([text.splitlines()[0]]), [])
        tail = text[last_break + 1 :]
        tail_fields = next(csv.reader([tail]), [])
        if len(tail_fields) != len(header):
            text = text[: last_break + 1]
    try:
        frame = pd.read_csv(
            StringIO(text),
            dtype=str,
            skipinitialspace=True,
            # SU2 pads quoted header fields before commas.  pandas' Python
            # engine rejects that official formatting, while the C engine
            # accepts it and we normalize the column whitespace below.
            engine="c",
            keep_default_na=False,
        )
    except (pd.errors.ParserError, UnicodeError, ValueError):
        raise HistoryParseError("HISTORY_CSV_INVALID") from None
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [name for name in _REQUIRED if name not in frame.columns]
    if missing:
        raise HistoryParseError("HISTORY_COLUMNS_MISSING")
    if frame.empty:
        return Su2History(source_path=resolved, samples=())

    # SU2 can append a repeated header when a run is resumed.
    frame = frame[
        frame["Inner_Iter"].astype(str).str.strip() != "Inner_Iter"
    ]
    samples: list[HistorySample] = []
    for _, row in frame.iterrows():
        values = {
            name: _finite_value(row[name], required=True)
            for name in _REQUIRED
        }
        optional = {
            name: (
                _finite_value(row[name], required=True)
                if name in frame.columns
                else None
            )
            for name in _OPTIONAL
        }
        iteration_value = values["Inner_Iter"]
        if (
            iteration_value < 0
            or not float(iteration_value).is_integer()
        ):
            raise HistoryParseError("HISTORY_ROW_INVALID")
        samples.append(
            HistorySample(
                iteration=int(iteration_value),
                rms_pressure=values["rms[P]"],
                rms_tke=values["rms[k]"],
                rms_omega=values["rms[w]"],
                cd=optional["CD"],
                cl=optional["CL"],
                force_x=optional["CFx"],
                force_y=optional["CFy"],
                force_z=optional["CFz"],
            )
        )
    return Su2History(source_path=resolved, samples=tuple(samples))


def _finite_value(value: object, *, required: bool) -> float | None:
    if value is None or pd.isna(value) or not str(value).strip():
        if required:
            raise HistoryParseError("HISTORY_ROW_INVALID")
        return None
    try:
        number = float(str(value).strip())
    except ValueError:
        raise HistoryParseError("HISTORY_ROW_INVALID") from None
    if not math.isfinite(number):
        raise HistoryParseError("HISTORY_NONFINITE")
    return number
