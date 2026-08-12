from __future__ import annotations

from pathlib import Path

from phoenix_aero_lite.app.workflow import (
    ResumableWorkflow,
    StepOutcome,
    WorkflowStepDefinition,
)


def test_resume_reuses_only_hash_valid_completed_steps(tmp_path: Path):
    calls: list[str] = []

    def step(name: str, dependency: str | None = None):
        def execute(context):
            calls.append(name)
            path = tmp_path / f"{name}.txt"
            path.write_text(name, encoding="utf-8")
            context[name] = name
            return StepOutcome((path,), {"value": name})

        def restore(context, record):
            context[name] = record.metadata["value"]

        return WorkflowStepDefinition(
            name,
            (dependency,) if dependency else (),
            execute,
            restore,
        )

    workflow = ResumableWorkflow(
        tmp_path / "case",
        (
            step("stage"),
            step("mesh", "stage"),
            step("solve", "mesh"),
        ),
    )
    first = workflow.run("a" * 64)
    assert first.executed_steps == ("stage", "mesh", "solve")
    second = workflow.run("a" * 64)
    assert second.reused_steps == ("stage", "mesh", "solve")
    assert calls == ["stage", "mesh", "solve"]

    (tmp_path / "mesh.txt").write_text("tampered", encoding="utf-8")
    third = workflow.run("a" * 64)
    assert third.reused_steps == ("stage",)
    assert third.executed_steps == ("mesh", "solve")


def test_parameter_fingerprint_change_invalidates_all_downstream(tmp_path: Path):
    calls: list[str] = []

    def execute(context):
        calls.append("run")
        artifact = tmp_path / f"artifact-{len(calls)}.txt"
        artifact.write_text(str(len(calls)), encoding="utf-8")
        return StepOutcome((artifact,), {})

    workflow = ResumableWorkflow(
        tmp_path / "case",
        (WorkflowStepDefinition("stage", (), execute),),
    )
    workflow.run("a" * 64)
    result = workflow.run("b" * 64)
    assert result.executed_steps == ("stage",)
    assert calls == ["run", "run"]


def test_crash_leaves_last_complete_step_reusable(tmp_path: Path):
    attempts = 0

    def first(context):
        path = tmp_path / "first.txt"
        path.write_text("done", encoding="utf-8")
        return StepOutcome((path,), {})

    def flaky(context):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("simulated crash")
        path = tmp_path / "second.txt"
        path.write_text("done", encoding="utf-8")
        return StepOutcome((path,), {})

    workflow = ResumableWorkflow(
        tmp_path / "case",
        (
            WorkflowStepDefinition("first", (), first),
            WorkflowStepDefinition("second", ("first",), flaky),
        ),
    )
    try:
        workflow.run("c" * 64)
    except RuntimeError:
        pass
    resumed = workflow.run("c" * 64)
    assert resumed.reused_steps == ("first",)
    assert resumed.executed_steps == ("second",)


def test_explicit_step_fingerprints_recompute_only_invalidated_dag_nodes(tmp_path: Path):
    calls: list[str] = []

    def definition(name: str, dependency: str | None, fingerprint: str):
        def execute(_context):
            calls.append(name)
            artifact = tmp_path / f"{name}-{calls.count(name)}.txt"
            artifact.write_text(name, encoding="utf-8")
            return StepOutcome((artifact,), {})

        return WorkflowStepDefinition(
            name,
            (dependency,) if dependency else (),
            execute,
            input_fingerprint=fingerprint,
        )

    ResumableWorkflow(
        tmp_path / "case",
        (
            definition("mesh", None, "a" * 64),
            definition("solve", "mesh", "b" * 64),
            definition("report", "solve", "c" * 64),
        ),
    ).run("f" * 64)
    changed_report = ResumableWorkflow(
        tmp_path / "case",
        (
            definition("mesh", None, "a" * 64),
            definition("solve", "mesh", "b" * 64),
            definition("report", "solve", "d" * 64),
        ),
    ).run("f" * 64)

    assert changed_report.reused_steps == ("mesh", "solve")
    assert changed_report.executed_steps == ("report",)
    assert calls == ["mesh", "solve", "report", "report"]


def test_legacy_step_without_input_fingerprint_is_not_reused_by_fingerprinted_step(
    tmp_path: Path,
):
    calls = 0

    def execute(_context):
        nonlocal calls
        calls += 1
        artifact = tmp_path / f"artifact-{calls}.txt"
        artifact.write_text(str(calls), encoding="utf-8")
        return StepOutcome((artifact,), {})

    case = tmp_path / "case"
    ResumableWorkflow(
        case,
        (WorkflowStepDefinition("solve", (), execute),),
    ).run("f" * 64)
    migrated = ResumableWorkflow(
        case,
        (
            WorkflowStepDefinition(
                "solve", (), execute, input_fingerprint="a" * 64
            ),
        ),
    ).run("f" * 64)

    assert migrated.executed_steps == ("solve",)
    assert calls == 2


def test_reused_steps_preserve_the_manifest_producer_identity(tmp_path: Path):
    def execute(_context):
        artifact = tmp_path / "artifact.txt"
        artifact.write_text("verified", encoding="utf-8")
        return StepOutcome((artifact,), {})

    workflow = ResumableWorkflow(
        tmp_path / "case",
        (WorkflowStepDefinition("mesh", (), execute, input_fingerprint="a" * 64),),
    )

    first = workflow.run("f" * 64, producer_id="job-a")
    reused = workflow.run("f" * 64, producer_id="job-b")

    assert first.stage_sources == {"mesh": "job-a"}
    assert reused.reused_steps == ("mesh",)
    assert reused.stage_sources == {"mesh": "job-a"}
