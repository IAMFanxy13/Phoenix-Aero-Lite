from phoenix_aero_lite.web.diagnostics import diagnostic_for, diagnostics_for_codes


def test_known_diagnostic_explains_problem_impact_action_and_field_access():
    item = diagnostic_for("CONVERGENCE_STAGNATED")

    assert "没有继续稳定" in item.title_zh
    assert item.causes_zh
    assert "工程结论" in item.impact_zh
    assert item.action_zh
    assert item.can_view_fields is True
    assert item.conservative_retry_allowed is True


def test_diagnostics_keep_machine_code_and_deduplicate():
    items = diagnostics_for_codes(("MESH_FAILED", "MESH_FAILED", "NEW_CODE"))

    assert [item.code for item in items] == ["MESH_FAILED", "NEW_CODE"]
    assert items[0].can_view_fields is False
    assert items[1].title_zh == "操作或计算没有完成"


def test_computed_but_unverified_y_plus_has_truthful_chinese_diagnostic():
    item = diagnostic_for("Y_PLUS_EVIDENCE_NOT_VERIFIED")

    assert "已计算" in item.happened_zh
    assert "尚未验证" in item.title_zh
    assert item.can_view_fields is True
    assert item.conservative_retry_allowed is False
