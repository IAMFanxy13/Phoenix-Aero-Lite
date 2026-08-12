"""Deterministic non-interactive engineering charts."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties

from phoenix_aero_lite.solver.su2_history import Su2History


class ChartError(ValueError):
    """Stable chart generation failure."""


def generate_convergence_chart(
    history: Su2History,
    output_path: Path,
) -> Path:
    """Render SU2 residuals to a PNG using the non-interactive Agg canvas."""

    if not isinstance(history, Su2History) or not history.samples:
        raise ChartError("CHART_HISTORY_EMPTY")
    output = _validate_png_output(output_path)
    figure = Figure(figsize=(9.0, 4.8), dpi=120, layout="constrained")
    canvas = FigureCanvasAgg(figure)
    axes = figure.add_subplot(1, 1, 1)
    chinese_font = _chinese_font()
    iterations = [sample.iteration for sample in history.samples]
    axes.plot(
        iterations,
        [sample.rms_pressure for sample in history.samples],
        label="rms[P]",
        linewidth=1.6,
    )
    axes.plot(
        iterations,
        [sample.rms_tke for sample in history.samples],
        label="rms[k]",
        linewidth=1.2,
    )
    axes.plot(
        iterations,
        [sample.rms_omega for sample in history.samples],
        label="rms[w]",
        linewidth=1.2,
    )
    if chinese_font is None:
        axes.set_title("SU2 convergence history")
        axes.set_xlabel("Inner iteration")
        axes.set_ylabel("log10 residual")
    else:
        axes.set_title("SU2 收敛历史", fontproperties=chinese_font)
        axes.set_xlabel("内迭代", fontproperties=chinese_font)
        axes.set_ylabel("log10 残差", fontproperties=chinese_font)
    axes.grid(True, alpha=0.25)
    axes.legend()
    buffer = BytesIO()
    canvas.print_png(buffer)
    try:
        with output.open("xb") as destination:
            destination.write(buffer.getvalue())
    except FileExistsError:
        raise ChartError("CHART_OUTPUT_COLLISION") from None
    except OSError:
        raise ChartError("CHART_WRITE_FAILED") from None
    return output.resolve(strict=True)


def _chinese_font() -> FontProperties | None:
    candidates = (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return FontProperties(fname=str(path))
    return None


def _validate_png_output(path: Path) -> Path:
    if (
        not isinstance(path, Path)
        or path.suffix.lower() != ".png"
        or ".." in path.parts
    ):
        raise ChartError("CHART_OUTPUT_UNSAFE")
    requested = path if path.is_absolute() else Path.cwd() / path
    _reject_redirecting_ancestors(requested.parent)
    requested.parent.mkdir(parents=True, exist_ok=True)
    output = requested.parent.resolve(strict=True) / requested.name
    if output.exists():
        raise ChartError("CHART_OUTPUT_COLLISION")
    return output


def _reject_redirecting_ancestors(path: Path) -> None:
    current = path
    while True:
        if current.exists() and (
            current.is_symlink()
            or (hasattr(current, "is_junction") and current.is_junction())
        ):
            raise ChartError("CHART_OUTPUT_UNSAFE")
        if current.parent == current:
            return
        current = current.parent
