from fastapi.testclient import TestClient

from phoenix_aero_lite.web.app import create_app
from phoenix_aero_lite.web.jobs import LocalJobService


def test_chinese_page_and_local_assets_are_served(tmp_path):
    service = LocalJobService(tmp_path / "jobs", runner=lambda *_args: None)
    app = create_app(tmp_path, job_service=service)

    with TestClient(app) as http:
        page = http.get("/")
        css = http.get("/static/app.css")
        javascript = http.get("/static/app.js")

    assert page.status_code == 200
    for text in (
        "上传模型",
        "确认模型",
        "设置工况",
        "开始分析",
        "三维模型",
        "来源与可信度",
        "专业诊断",
        "历史任务",
    ):
        assert text in page.text
    assert 'id="model-viewer"' in page.text
    assert 'id="wing-selection"' in page.text
    assert 'id="reset-wing-selection"' in page.text
    assert 'id="pick-nose"' in page.text
    assert 'id="pick-up"' in page.text
    assert 'id="undo-orientation"' in page.text
    assert 'data-restore-parameter="s_ref_m2"' in page.text
    assert 'data-restore-parameter="c_ref_m"' in page.text
    assert 'id="advanced-settings"' in page.text
    assert 'id="preflight-status"' in page.text
    assert 'id="preflight-details"' in page.text
    assert 'id="preset-description"' in page.text
    assert 'id="grid-study-view"' in page.text
    assert 'id="grid-study-levels"' in page.text
    assert 'data-view="yplus"' in page.text
    assert 'aria-label="壁面 Y+ 云图"' in page.text
    advanced = page.text.split('id="advanced-settings"', 1)[1].split(
        "</details>", 1
    )[0]
    assert 'name="s_ref_m2"' in advanced
    assert 'name="c_ref_m"' in advanced
    assert 'name="max_iterations"' in advanced
    assert "cdn" not in page.text.casefold()
    assert css.status_code == 200
    assert "--accent" in css.text
    assert javascript.status_code == 200
    assert "/api/jobs" in javascript.text
    assert "/api/grid-studies" in javascript.text
    assert "/scenes/y-plus" in javascript.text
    assert "['computed', 'measured', 'verified'].includes" in javascript.text
    assert "showGridStudy" in javascript.text
    assert "loadRequestedGridStudy" in javascript.text
    assert "setCurrentResultUrl" in javascript.text
    assert "gridStudyReasonText" in javascript.text
    assert "GRID_CELL_COUNTS_NOT_REFINED" in javascript.text
    assert "targetCellSizeInput.step = 'any'" in javascript.text
    assert "/api/models" in javascript.text
    assert "/api/preflight" in javascript.text
    assert "/api/presets" in javascript.text
    assert "phoenix-surface-selection" in javascript.text
    assert "phoenix-orientation-point" in javascript.text
    assert "phoenix-pick-mode" in javascript.text
    assert "/wing-surfaces" in javascript.text
    assert "requestJson" in javascript.text
    assert "AbortController" in javascript.text
    assert "schedulePoll(nextPollDelay" in javascript.text
    assert "pendingWingSelection" in javascript.text
    assert "modelRequestSequence" in javascript.text
    assert "sceneRequestSequence" in javascript.text
    assert "scientificUseText" in javascript.text
    assert "likely_converged" in javascript.text
    assert "oscillating" in javascript.text
    assert "diagnostic_only" in javascript.text
    service.shutdown()


def test_workbench_uses_icon_first_navigation_without_hiding_evidence(tmp_path):
    """Catch regressions that turn the approved scan-friendly UI back into prose."""
    service = LocalJobService(tmp_path / "jobs", runner=lambda *_args: None)
    app = create_app(tmp_path, job_service=service)

    with TestClient(app) as http:
        page = http.get("/")

    assert page.status_code == 200
    for icon in ("🛩️", "🧭", "🪽", "🌬️", "⚙️", "🌈", "📊", "📁", "🔬"):
        assert f'data-icon="{icon}"' in page.text
    for short_label in ("上传", "方向", "主翼", "工况", "分析", "结果", "网格", "历史"):
        assert f">{short_label}<" in page.text
    assert "来源与可信度" in page.text
    assert "专业诊断" in page.text
    assert 'aria-label="三维模型"' in page.text
    assert 'aria-label="开始分析"' in page.text
    service.shutdown()
