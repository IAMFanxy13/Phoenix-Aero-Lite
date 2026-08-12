"""Tests for immutable, SI-only aerodynamic parameter models."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from phoenix_aero_lite.models.errors import ParameterValidationError
from phoenix_aero_lite.models.parameters import (
    AircraftParameters,
    CaseParameters,
    FlowParameters,
    MeshMode,
    MeshParameters,
    OutputParameters,
    ReferenceParameters,
    SolverParameters,
)


def valid_case() -> CaseParameters:
    return CaseParameters(
        flow=FlowParameters(
            velocity_m_s=15.0,
            density_kg_m3=1.225,
            dynamic_viscosity_pa_s=1.7894e-5,
            angle_of_attack_deg=6.0,
        ),
        reference=ReferenceParameters(s_ref_m2=0.8, c_ref_m=0.3),
        aircraft=AircraftParameters(mass_kg=12.0),
        mesh=MeshParameters(mode=MeshMode.PREVIEW, target_cell_size_m=0.05),
        solver=SolverParameters(max_iterations=500),
        output=OutputParameters(output_directory=Path("cases/preview")),
    )


@pytest.mark.parametrize(
    ("parameters", "code"),
    [
        (FlowParameters(0.0, 1.225, 1.7894e-5, 0.0), "FLOW_VELOCITY_MUST_BE_POSITIVE"),
        (FlowParameters(-1.0, 1.225, 1.7894e-5, 0.0), "FLOW_VELOCITY_MUST_BE_POSITIVE"),
        (FlowParameters(15.0, 0.0, 1.7894e-5, 0.0), "FLOW_DENSITY_MUST_BE_POSITIVE"),
        (FlowParameters(15.0, 1.225, 0.0, 0.0), "FLOW_VISCOSITY_MUST_BE_POSITIVE"),
        (FlowParameters(15.0, 1.225, 1.7894e-5, 45.1), "ANGLE_OF_ATTACK_OUT_OF_RANGE"),
        (MeshParameters(MeshMode.PREVIEW, 0.0), "MESH_TARGET_CELL_SIZE_MUST_BE_POSITIVE"),
        (SolverParameters(0), "SOLVER_MAX_ITERATIONS_MUST_BE_POSITIVE"),
        (AircraftParameters(0.0), "AIRCRAFT_MASS_MUST_BE_POSITIVE"),
    ],
)
def test_invalid_parameters_return_stable_chinese_issues(parameters, code):
    issues = parameters.validate()

    assert [issue.code for issue in issues] == [code]
    assert issues[0].text_zh


def test_flow_accepts_boundary_angles():
    assert FlowParameters(15.0, 1.225, 1.7894e-5, -45.0).validate() == ()
    assert FlowParameters(15.0, 1.225, 1.7894e-5, 45.0).validate() == ()


def test_parameter_values_are_immutable():
    flow = valid_case().flow

    with pytest.raises(FrozenInstanceError):
        flow.velocity_m_s = 20.0


def test_case_validation_collects_focused_model_issues():
    case = CaseParameters(
        flow=FlowParameters(0.0, 0.0, 0.0, 90.0),
        reference=ReferenceParameters(0.0, 0.0),
        aircraft=AircraftParameters(0.0),
        mesh=MeshParameters(MeshMode.PREVIEW, 0.0),
        solver=SolverParameters(0),
        output=OutputParameters(Path("cases/preview")),
    )

    assert [issue.code for issue in case.validate()] == [
        "FLOW_VELOCITY_MUST_BE_POSITIVE",
        "FLOW_DENSITY_MUST_BE_POSITIVE",
        "FLOW_VISCOSITY_MUST_BE_POSITIVE",
        "ANGLE_OF_ATTACK_OUT_OF_RANGE",
        "REFERENCE_AREA_MUST_BE_POSITIVE",
        "REFERENCE_CHORD_MUST_BE_POSITIVE",
        "AIRCRAFT_MASS_MUST_BE_POSITIVE",
        "MESH_TARGET_CELL_SIZE_MUST_BE_POSITIVE",
        "SOLVER_MAX_ITERATIONS_MUST_BE_POSITIVE",
    ]


def test_case_json_round_trip_preserves_si_values_and_paths():
    case = valid_case()

    restored = CaseParameters.from_json(case.to_json())

    assert restored == case
    assert restored.mesh.mode is MeshMode.PREVIEW
    assert restored.output.output_directory == Path("cases/preview")


@pytest.mark.parametrize(
    "payload",
    [
        '{"flow":{"velocity_m_s":NaN}}',
        '{"flow":{"velocity_m_s":Infinity}}',
        '{"flow":{"velocity_m_s":-Infinity}}',
    ],
)
def test_case_json_rejects_non_finite_numbers(payload):
    with pytest.raises(ParameterValidationError) as error:
        CaseParameters.from_json(payload)

    assert error.value.issues[0].code == "PARAMETERS_JSON_NON_FINITE_NUMBER"
    assert error.value.issues[0].text_zh


def test_case_json_rejects_unknown_fields():
    payload = valid_case().to_dict() | {"unapproved": True}

    with pytest.raises(ParameterValidationError) as error:
        CaseParameters.from_dict(payload)

    assert error.value.issues[0].code == "PARAMETERS_UNKNOWN_FIELD"


def test_case_json_rejects_an_empty_output_directory():
    payload = valid_case().to_dict()
    payload["output"] = {"output_directory": ""}

    with pytest.raises(ParameterValidationError) as error:
        CaseParameters.from_dict(payload)

    assert error.value.issues[0].code == "OUTPUT_DIRECTORY_MUST_BE_PROVIDED"
