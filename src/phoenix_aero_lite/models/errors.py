"""Stable domain validation issues exposed to the CLI and GUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


_CHINESE_TEXT: dict[str, str] = {
    "FLOW_VELOCITY_MUST_BE_POSITIVE": "来流速度必须大于零。",
    "FLOW_DENSITY_MUST_BE_POSITIVE": "空气密度必须大于零。",
    "FLOW_VISCOSITY_MUST_BE_POSITIVE": "动力黏度必须大于零。",
    "ANGLE_OF_ATTACK_OUT_OF_RANGE": "攻角必须在 -45 到 45 度之间。",
    "REFERENCE_AREA_MUST_BE_POSITIVE": "参考面积必须大于零。",
    "REFERENCE_CHORD_MUST_BE_POSITIVE": "参考弦长必须大于零。",
    "AIRCRAFT_MASS_MUST_BE_POSITIVE": "飞机质量必须大于零。",
    "MESH_MODE_INVALID": "网格模式必须为 preview、standard 或 fine。",
    "MESH_TARGET_CELL_SIZE_MUST_BE_POSITIVE": "目标网格尺寸必须大于零。",
    "SOLVER_MAX_ITERATIONS_MUST_BE_POSITIVE": "最大迭代次数必须为正整数。",
    "OUTPUT_DIRECTORY_MUST_BE_PROVIDED": "必须提供输出目录。",
    "PARAMETER_VALUE_MUST_BE_FINITE": "参数值必须是有限数值。",
    "PARAMETERS_JSON_NON_FINITE_NUMBER": "JSON 输入不允许 NaN 或 Infinity。",
    "PARAMETERS_JSON_INVALID": "参数 JSON 格式无效。",
    "PARAMETERS_UNKNOWN_FIELD": "参数中包含未识别的字段。",
    "PARAMETERS_REQUIRED_FIELD_MISSING": "参数缺少必需字段。",
    "PARAMETERS_FIELD_TYPE_INVALID": "参数字段类型无效。",
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A machine-stable validation code with Chinese display text."""

    code: str
    text_zh: str

    @property
    def text(self) -> str:
        """Alias retained for presentation layers that use a generic text field."""

        return self.text_zh


def issue_for(code: str) -> ValidationIssue:
    """Create a validation issue from the central, versioned message catalogue."""

    return ValidationIssue(code=code, text_zh=_CHINESE_TEXT[code])


class ParameterValidationError(ValueError):
    """Raised when strict parameter deserialization or validation fails."""

    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__(", ".join(issue.code for issue in self.issues))
