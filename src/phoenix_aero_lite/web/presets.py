"""Backend-owned analysis presets and their scientific evidence limits."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Mapping

from phoenix_aero_lite.models.parameters import MeshMode


@dataclass(frozen=True, slots=True)
class AnalysisPreset:
    code: str
    title_zh: str
    purpose_zh: str
    runtime_zh: str
    resource_zh: str
    runs_solver: bool
    mesh_strategy: str
    boundary_layer: str
    target_y_plus: float | None
    grid_levels: int
    evidence_ceiling: str
    allows_user_override: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_PRESETS = MappingProxyType(
    {
        "geometry_check": AnalysisPreset(
            "geometry_check",
            "几何检查",
            "检查 STEP 尺寸、封闭性、曲面和主翼选择，不运行 CFD。",
            "通常 1–5 分钟",
            "低",
            False,
            "surface_inspection_only",
            "not_applicable",
            None,
            0,
            "geometry_only",
            False,
        ),
        "trend": AnalysisPreset(
            "trend",
            "初步趋势",
            "用较粗网格发现方向、设置和明显流动趋势，不用于最终工程数字。",
            "通常 10–45 分钟",
            "中低",
            True,
            "preview_external_volume",
            "not_guaranteed",
            None,
            1,
            "diagnostic_only",
            False,
        ),
        "standard": AnalysisPreset(
            "standard",
            "标准分析",
            "生成并审计近壁层；只有网格、Y+ 和收敛全部通过才允许工程使用。",
            "通常 1–6 小时，取决于模型和电脑",
            "中高",
            True,
            "standard_external_volume",
            "enabled_and_audited",
            1.0,
            1,
            "engineering_if_all_gates_pass",
            False,
        ),
        "grid_study": AnalysisPreset(
            "grid_study",
            "三档网格研究",
            "创建粗、中、细三个独立任务，并在三档均收敛后计算 GCI。",
            "通常为标准分析的 3–6 倍",
            "高",
            False,
            "coarse_medium_fine_family",
            "enabled_and_audited",
            1.0,
            3,
            "grid_sensitivity",
            False,
        ),
        "custom": AnalysisPreset(
            "custom",
            "自定义",
            "由专业用户设置网格和迭代预算；仍执行相同科学门槛。",
            "由设置决定",
            "由设置决定",
            True,
            "user_configured",
            "user_configured_and_audited",
            None,
            1,
            "determined_by_evidence",
            True,
        ),
    }
)


def analysis_presets() -> Mapping[str, AnalysisPreset]:
    return _PRESETS


def resolve_solver_preset(
    name: str,
    *,
    requested_iterations: int | None = None,
) -> tuple[MeshMode, int]:
    normalized = str(name).strip().casefold()
    if normalized == "trend":
        return MeshMode.PREVIEW, 300
    if normalized == "fast":
        return MeshMode.PREVIEW, requested_iterations or 300
    if normalized == "standard":
        return MeshMode.STANDARD, 800
    if normalized == "fine":
        return MeshMode.FINE, requested_iterations or 1200
    if normalized == "custom":
        return MeshMode.STANDARD, requested_iterations or 500
    raise ValueError("ANALYSIS_MODE_REQUIRES_SEPARATE_WORKFLOW")
