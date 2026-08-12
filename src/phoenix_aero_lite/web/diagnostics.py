"""User-facing Chinese diagnostics kept separate from machine error codes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    title_zh: str
    happened_zh: str
    causes_zh: tuple[str, ...]
    impact_zh: str
    action_zh: tuple[str, ...]
    can_view_fields: bool
    conservative_retry_allowed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "title_zh": self.title_zh,
            "happened_zh": self.happened_zh,
            "causes_zh": list(self.causes_zh),
            "impact_zh": self.impact_zh,
            "action_zh": list(self.action_zh),
            "can_view_fields": self.can_view_fields,
            "conservative_retry_allowed": self.conservative_retry_allowed,
        }


_DIAGNOSTICS = {
    "CONVERGENCE_STAGNATED": Diagnostic(
        "CONVERGENCE_STAGNATED",
        "计算后期没有继续稳定",
        "残差或升阻力系数在后期停滞，本次数据只能用于观察趋势。",
        ("网格分辨率不足或局部质量较差", "最大迭代数不足", "当前工况存在明显分离或非定常流动"),
        "CL、CD 和云图不能作为最终工程结论；已有真实场数据仍可带警告查看。",
        ("先查看收敛曲线和系数振荡", "可使用更稳妥设置创建一次新任务重算", "若仍停滞，应检查网格、近壁层和工况"),
        True,
        True,
    ),
    "RESIDUAL_STAGNATION": Diagnostic(
        "RESIDUAL_STAGNATION",
        "残差下降停滞",
        "求解器仍能运行，但控制方程误差没有继续明显下降。",
        ("网格或边界条件限制", "松弛/迭代预算不足", "流动本身具有非定常性"),
        "结果只适合趋势检查，不能隐去该风险。",
        ("查看专业诊断中的残差和 CL/CD 后期波动", "使用更稳妥设置最多重算一次"),
        True,
        True,
    ),
    "NEAR_WALL_LAYER_NOT_VALIDATED": Diagnostic(
        "NEAR_WALL_LAYER_NOT_VALIDATED",
        "近壁层尚未验证",
        "当前网格没有足够证据证明机体表面附近的黏性流动被正确解析。",
        ("缺少边界层棱柱网格", "Y+ 未计算或不满足所用壁面处理要求"),
        "阻力和分离位置不可靠；压力趋势可查看，但黏性阻力不能作定量结论。",
        ("切换到细致网格并检查边界层设置", "在专业诊断中确认 Y+ 与湍流模型要求"),
        True,
        True,
    ),
    "Y_PLUS_EVIDENCE_NOT_VERIFIED": Diagnostic(
        "Y_PLUS_EVIDENCE_NOT_VERIFIED",
        "壁面 Y+ 尚未验证",
        "SU2 已计算真实壁面 Y+，但其范围、覆盖率或网格独立性尚未满足工程门槛。",
        ("部分表面 Y+ 超出当前壁面处理目标", "近壁层覆盖或网格研究证据不足"),
        "Y+ 云图可用于定位问题，但阻力和分离结论不能升级为工程结论。",
        ("查看 Y+ 云图中的高值区域", "检查近壁层覆盖并完成三档网格研究"),
        True,
        False,
    ),
    "MESH_FAILED": Diagnostic(
        "MESH_FAILED",
        "外流场网格生成失败",
        "Gmsh 没有生成可供 SU2 使用的有效体网格。",
        ("STEP 存在缝隙、重叠面或极小特征", "局部网格尺寸过小", "布尔减运算后边界标签或体拓扑异常"),
        "没有真实求解结果，不能显示或生成仿真云图。",
        ("查看几何检查中的风险曲面", "可用稍粗的保守网格最多重试一次", "仍失败时回到 CAD 修复几何"),
        False,
        True,
    ),
    "MESH_INVALID_SURFACE_ELEMENTS": Diagnostic(
        "MESH_INVALID_SURFACE_ELEMENTS",
        "机体表面仍有无效网格单元",
        "Gmsh 明确报告曲面三角形无效，软件已在启动 SU2 前停止。",
        ("STEP 曲面参数化在局部退化", "曲面存在极窄区域或坏曲线", "当前网格尺寸不足以解析该区域"),
        "边界几何不可靠会污染体网格和压力结果，因此不允许显示工程云图。",
        ("查看几何检查中的问题曲面", "尝试更细的官方 Gmsh 曲面网格", "仍失败时回到 CAD 修复对应曲面"),
        False,
        False,
    ),
    "SOLVER_FAILED": Diagnostic(
        "SOLVER_FAILED",
        "SU2 求解没有正常完成",
        "SU2 退出或未产生完整历史与流场产物。",
        ("网格/边界标记不兼容", "数值发散、NaN 或运行时依赖错误", "磁盘、权限或外部进程异常"),
        "本次没有可用于工程判断的完整结果；只显示实际存在的排错产物。",
        ("查看专业诊断中的 SU2 stdout/stderr", "先解决明确的 DLL、权限或边界错误，再重算"),
        False,
        False,
    ),
    "JOB_INTERRUPTED_BY_RESTART": Diagnostic(
        "JOB_INTERRUPTED_BY_RESTART",
        "程序关闭或重启中断了计算",
        "旧任务没有继续在后台运行，历史记录已保留。",
        ("用户关闭启动窗口", "系统重启或进程异常终止"),
        "未完成的结果无效。",
        ("确认后端保持运行后重新提交任务",),
        False,
        True,
    ),
    "STREAMLINES_EMPTY": Diagnostic(
        "STREAMLINES_EMPTY",
        "真实体流场没有生成可显示的流线",
        "从上游种子平面向下游积分后没有得到有效轨迹。",
        ("体流场缺少有效速度", "种子平面不在流体域内", "流场或网格产物不完整"),
        "不会生成伪流线；压力和速度结果仅在各自产物有效时继续可看。",
        ("检查体流场速度字段和外流场范围", "确认来流方向后重新生成"),
        True,
        False,
    ),
}


def diagnostic_for(code: str) -> Diagnostic:
    normalized = str(code).strip()
    return _DIAGNOSTICS.get(
        normalized,
        Diagnostic(
            normalized or "UNKNOWN_ERROR",
            "操作或计算没有完成",
            "软件保留了原始错误码，但当前没有更具体的自动解释。",
            ("输入、几何、外部工具或运行环境出现异常",),
            "不能仅凭程序结束判断结果可用。",
            ("展开专业诊断查看原始错误码和日志", "修复明确原因后创建新任务"),
            False,
            False,
        ),
    )


def diagnostics_for_codes(codes: tuple[str, ...]) -> tuple[Diagnostic, ...]:
    unique = []
    seen = set()
    for code in codes:
        if code and code not in seen:
            unique.append(diagnostic_for(code))
            seen.add(code)
    return tuple(unique)
