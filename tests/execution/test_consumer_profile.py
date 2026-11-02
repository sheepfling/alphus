"""Keep the documented consumer profile valid and tool ownership explicit."""

from __future__ import annotations

import tomllib
from pathlib import Path

from alphus.config import CommandRunStep, RuleRunStep, load_config

_POLICY = Path("examples/consumer/quality-gates.toml")


def test_starter_policy_has_one_scoped_command_and_no_global_inventory() -> None:
    config = load_config(Path("examples/starter/quality-gates.toml"))
    assert config.files is None
    orchestration = config.orchestration
    assert orchestration is not None
    plan = orchestration.resolve_profile("check")
    assert plan is not None
    assert plan.steps == ("Markdown style",)
    step = orchestration.steps[0]
    assert isinstance(step, CommandRunStep)
    assert step.files is not None
    assert step.fix_argv == ("rumdl", "fmt", "{files}")


def test_manual_matrix_kernel_example_is_scoped_and_provisional() -> None:
    config = load_config(Path("examples/numerics/manual-matrix-kernels.toml"))
    assert config.files is not None
    assert config.files.include == ("src/numerics/*.py", "src/geometry/*.py")
    policy = config.checks.manual_matrix_kernels
    assert policy is not None
    assert policy.source_paths == ("src/numerics/*.py",)
    elimination_policy = config.checks.manual_elimination
    assert elimination_policy is not None
    assert elimination_policy.function_names == ("invert_matrix",)
    assert elimination_policy.matrix_name == "matrix"
    churn_policy = config.checks.array_representation_churn
    assert churn_policy is not None
    assert churn_policy.loop_contracts[0].path == "src/numerics/kernels.py"
    assert churn_policy.loop_contracts[0].function == "process_batches"
    assert churn_policy.loop_contracts[0].array_variable == "batch"
    normalization_policy = config.checks.manual_quaternion_normalization
    assert normalization_policy is not None
    assert normalization_policy.components == ("w", "x", "y", "z")
    assert normalization_policy.rotation_consumer_helpers == ("Rotation.from_quat",)
    inversion_policy = config.checks.manual_quaternion_inversion
    assert inversion_policy is not None
    assert inversion_policy.components == ("w", "x", "y", "z")
    vector_rotation_policy = config.checks.manual_quaternion_vector_rotation
    assert vector_rotation_policy is not None
    assert vector_rotation_policy.vector_components == ("vx", "vy", "vz")
    assert vector_rotation_policy.multiplication_helpers == ("multiply",)
    matrix_policy = config.checks.manual_quaternion_matrix_conversion
    assert matrix_policy is not None
    assert matrix_policy.convention == "active-column-scalar-first"
    frame_policy = config.checks.ecef_enu_transform
    assert frame_policy is not None
    assert frame_policy.source_frame == "ECEF"
    assert frame_policy.destination_frame == "ENU"
    assert frame_policy.operation == "displacement-vector"
    assert frame_policy.reference_ellipsoid == "WGS84"
    assert "pyproj.Transformer.from_pipeline" in frame_policy.preferred_helpers[0]
    ned_matrix_policy = config.checks.ecef_ned_matrix_transform
    assert ned_matrix_policy is not None
    assert ned_matrix_policy.destination_frame == "NED"
    assert ned_matrix_policy.axis_order == "north-east-down"
    assert ned_matrix_policy.vector_orientation == "column"
    assert ned_matrix_policy.output_shape == "matrix3x3"
    assert "pyproj.Transformer.from_pipeline" in ned_matrix_policy.preferred_helpers[0]
    ned_basis_policy = config.checks.ned_basis_vectors
    assert ned_basis_policy is not None
    assert ned_basis_policy.latitude_type == "geodetic"
    assert ned_basis_policy.output_representation == "basis3"
    assert ned_basis_policy.destination_frame == "GEODETIC_HORIZON"
    assert "pyproj.Transformer.from_pipeline" in ned_basis_policy.preferred_helpers[0]
    orchestration = config.orchestration
    assert orchestration is not None
    plan = orchestration.resolve_profile("numerical-review")
    assert plan is not None
    step = orchestration.steps[0]
    assert isinstance(step, RuleRunStep)
    assert step.rule == "manual-matrix-kernels"
    assert step.rollout == "provisional"
    assert "Quaternion product review" in plan.steps
    assert "Quaternion normalization review" in plan.steps
    assert "Quaternion inversion review" in plan.steps
    assert "Quaternion vector rotation review" in plan.steps
    assert "Quaternion matrix conversion review" in plan.steps
    assert "ECEF to ENU transform review" in plan.steps
    assert "ECEF to NED matrix review" in plan.steps
    assert "Manual elimination review" in plan.steps


def test_markdown_example_pairs_two_fixers_without_duplicate_missing_links() -> None:
    config = load_config(Path("examples/markdown/quality-gates.toml"))
    assert config.files is None
    orchestration = config.orchestration
    assert orchestration is not None
    plan = orchestration.resolve_profile("check")
    assert plan is not None
    assert plan.steps == ("Markdown style", "Markdown links and graph")
    assert all(
        isinstance(step, CommandRunStep) and step.fix_argv
        for step in orchestration.steps
    )
    mdrepo_config = tomllib.loads(
        Path("examples/markdown/mdrepo.toml").read_text(encoding="utf-8")
    )
    assert mdrepo_config["orphans"]["roots"] == ["README.md"]
    assert not mdrepo_config.get("links", {}).get("check-missing-targets", False)


def test_consumer_example_composes_portable_rules_and_native_tools() -> None:
    config = load_config(_POLICY)
    orchestration = config.orchestration
    assert orchestration is not None
    profile = orchestration.resolve_profile("check")
    assert profile is not None
    steps = {step.name: step for step in orchestration.steps}

    assert len(profile.steps) == 17
    assert [steps[name].kind for name in profile.steps[:7]] == ["rule"] * 7
    assert all(steps[name].kind == "command" for name in profile.steps[7:])
    assert isinstance(steps["Python structure"], RuleRunStep)
    assert isinstance(steps["Markdown links and graph"], CommandRunStep)
    assert steps["Markdown links and graph"].argv == (
        "{python}",
        "-m",
        "mdrepo",
        "--root",
        "{root}",
        "--config",
        "{root}/mdrepo.toml",
        "check",
        "{files}",
    )
    assert steps["Markdown links and graph"].fix_argv is not None
    assert steps["Markdown links and graph"].fix_argv[-2:] == ("fix", "{files}")
    assert steps["Markdown links and graph"].files is not None

    markdown = steps["Markdown style"]
    assert isinstance(markdown, CommandRunStep)
    assert markdown.argv == (
        "rumdl",
        "check",
        "--no-cache",
        "{files}",
    )
    assert markdown.fix_argv == ("rumdl", "fmt", "{files}")
    assert markdown.files is not None
    assert markdown.files.include == ("**/*.[mM][dD]", "*.[mM][dD]")

    assert steps["Python lint"].argv == (
        "{python}",
        "-m",
        "ruff",
        "check",
        "--force-exclude",
        "{files}",
    )
    assert steps["Python lint"].fix_argv == (
        "{python}",
        "-m",
        "ruff",
        "check",
        "--fix",
        "--force-exclude",
        "{files}",
    )
    assert "--force-exclude" in steps["Python format"].argv
    assert "--force-exclude" in steps["Python format"].fix_argv
    assert steps["Python types"].argv == (
        "pyright",
        "--pythonpath",
        "{python}",
        "src",
        "tests",
    )
    assert steps["Python tests"].argv == (
        "{python}",
        "-m",
        "pytest",
        "tests",
        "-q",
    )


def test_consumer_documentation_profile_has_only_native_doc_owners() -> None:
    config = load_config(_POLICY)
    orchestration = config.orchestration
    assert orchestration is not None
    profile = orchestration.resolve_profile("docs")
    assert profile is not None
    assert profile.steps == ("Markdown style", "Markdown links and graph")


def test_consumer_data_formats_have_separate_profiles_with_format_fixers() -> None:
    config = load_config(_POLICY)
    orchestration = config.orchestration
    assert orchestration is not None
    toml = orchestration.resolve_profile("toml")
    json_profile = orchestration.resolve_profile("json")
    check = orchestration.resolve_profile("check")

    assert toml is not None and toml.steps == ("TOML syntax", "TOML format")
    assert json_profile is not None and json_profile.steps == (
        "JSON syntax",
        "JSON format",
    )
    assert check is not None
    assert all(name in check.steps for name in (*toml.steps, *json_profile.steps))
    steps = {step.name: step for step in orchestration.steps}
    assert isinstance(steps["TOML format"], CommandRunStep)
    assert steps["TOML format"].fix_argv == ("taplo", "fmt", "{files}")
    assert isinstance(steps["JSON format"], CommandRunStep)
    assert steps["JSON format"].fix_argv == (
        "npm",
        "exec",
        "--no",
        "--",
        "prettier",
        "--write",
        "{files}",
    )
    assert steps["TOML syntax"].fix_argv is None
    assert steps["JSON syntax"].fix_argv is None
