from phoenix_aero_lite.models.provenance import (
    Confidence,
    ParameterSource,
    ProvenancedValue,
)


def test_user_override_retains_detected_value_source_and_rationale():
    detected = ProvenancedValue(
        name="s_ref_m2",
        unit="m²",
        detected_value=0.82,
        current_value=0.82,
        source=ParameterSource.SOFTWARE_COMPUTED,
        rationale="projected model estimate",
        confidence=Confidence.LOW,
        confirmed=False,
    )

    overridden = detected.with_user_value(0.91, confirmed=True, updated_at="now")

    assert overridden.detected_value == 0.82
    assert overridden.current_value == 0.91
    assert overridden.source is ParameterSource.USER_OVERRIDE
    assert overridden.original_source is ParameterSource.SOFTWARE_COMPUTED
    assert overridden.overridden is True
    assert overridden.confirmed is True
    assert overridden.updated_at == "now"
    assert overridden.to_dict()["confidence"] == "low"


def test_confidence_includes_explicit_unresolved_state():
    assert Confidence.UNRESOLVED.value == "unresolved"


def test_restore_detected_value_removes_user_override_but_retains_audit_time():
    detected = ProvenancedValue(
        name="span_m",
        unit="m",
        detected_value=2.0,
        current_value=2.0,
        source=ParameterSource.SOFTWARE_COMPUTED,
        rationale="bounding-box candidate",
        confidence=Confidence.MEDIUM,
        confirmed=False,
    )
    overridden = detected.with_user_value(2.1, confirmed=True, updated_at="first")

    restored = overridden.restore_detected(updated_at="second")

    assert restored.current_value == 2.0
    assert restored.source is ParameterSource.SOFTWARE_COMPUTED
    assert restored.original_source is ParameterSource.SOFTWARE_COMPUTED
    assert restored.overridden is False
    assert restored.confirmed is False
    assert restored.updated_at == "second"
