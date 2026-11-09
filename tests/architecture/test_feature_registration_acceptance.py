"""Prove one feature-local check reaches the real installed runtime path."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from alphus.execution.processes import run_captured_process
from alphus.support.git import run_git

_SELECTOR = "morphology-extension-probe"
_RULE_ID = "alphus/python/none/testing/morphology-extension-probe"
_REGISTRATION = '''"""Feature-local registration added by the acceptance fixture."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import (
    Category,
    Framework,
    RuleTag,
    Scope,
    rule_tag,
)
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import TestQualityPolicy

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="morphology-extension-probe",
    policy_field="test_quality",
    policy_model=TestQualityPolicy,
    output_shape="findings",
    summary="Exercises feature-local declaration through installed dispatch.",
    applies_to=("python",),
    domains=("acceptance",),
    requires_files=True,
)


ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="morphology-extension-probe",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.TESTING,
            "morphology-extension-probe",
        ),
    ),
    concern="extension-registration",
    claim_kind=ClaimKind.CONDITION,
    claim="The feature-local check executes through generated installed dispatch.",
    mechanisms=(DetectionMechanism.EXACT_RULE,),
    inspected_scope=("selected-source-files",),
    languages_formats=("python",),
    evidence_kinds=("path-line",),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


def _resolve_policy(config: QualityGateConfig) -> TestQualityPolicy:
    policy = config.checks.test_quality
    if policy is None:
        raise ValueError("the acceptance check requires test_quality policy")
    return policy


def _run(
    root: Path, files: Sequence[Path], policy: TestQualityPolicy
) -> list[Finding]:
    del policy
    if not files:
        return []
    return [
        Finding(
            rule_id=rule_tag(
                Scope.PYTHON,
                Framework.NONE,
                Category.TESTING,
                "morphology-extension-probe",
            ),
            path=files[0].relative_to(root).as_posix(),
            line=1,
            message="installed feature-local runner executed",
        )
    ]


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=_run,
    policy_resolver=_resolve_policy,
)
'''


def _copy_project(source: Path, target: Path) -> None:
    for name in ("pyproject.toml", "build_backend.py", "README.md"):
        shutil.copy2(source / name, target / name)
    shutil.copytree(
        source / "src",
        target / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(
        source / "scripts",
        target / "scripts",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def _git(directory: Path, *arguments: str) -> None:
    result = run_git(directory, *arguments)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


def _run(directory: Path, *arguments: str) -> str:
    result = run_captured_process(arguments, directory, timeout=240)
    assert result.returncode == 0, (
        f"command failed: {arguments!r}\\n"
        f"stdout:\\n{result.stdout}\\n"
        f"stderr:\\n{result.stderr}"
    )
    return result.stdout


def test_feature_local_extension_builds_and_dispatches_from_installed_wheel(
    pytestconfig: pytest.Config,
    tmp_path: Path,
) -> None:
    source = Path(pytestconfig.rootpath)
    project = tmp_path / "project"
    project.mkdir()
    _copy_project(source, project)
    _git(project, "init", "--quiet")
    _git(project, "config", "user.name", "Alphus Acceptance")
    _git(project, "config", "user.email", "alphus@example.invalid")
    _git(project, "add", "pyproject.toml", "build_backend.py", "README.md")
    _git(project, "add", "src", "scripts")
    _git(project, "commit", "--quiet", "-m", "acceptance fixture baseline")

    generated_inputs = {
        relative: (project / relative).read_bytes()
        for relative in (
            "pyproject.toml",
            "src/alphus/policy/base.py",
            "src/alphus/policy/catalog.py",
            "src/alphus/policy/orchestration.py",
        )
    }
    registration = (
        project
        / "src"
        / "alphus"
        / "gates"
        / "review"
        / "morphology_extension_probe.py"
    )
    registration.write_text(_REGISTRATION, encoding="utf-8")

    generator = _run(
        project,
        sys.executable,
        "-m",
        "scripts.generate_morphology_manifest",
        "--root",
        str(project),
    )
    assert generator == ""
    _run(
        project,
        sys.executable,
        "-m",
        "scripts.generate_runner_manifest",
        "--root",
        str(project),
    )

    generated_feature = (
        project / "src/alphus/policy/_generated_feature_definitions.py"
    ).read_text(encoding="utf-8")
    generated_rule_names = (
        project / "src/alphus/policy/_generated_quality_rule_names.py"
    ).read_text(encoding="utf-8")
    assert _SELECTOR in generated_feature
    assert _SELECTOR in generated_rule_names

    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _run(
        project,
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheelhouse),
        ".",
    )
    wheels = tuple(wheelhouse.glob("alphus-*.whl"))
    assert len(wheels) == 1

    installed = tmp_path / "installed"
    _run(
        tmp_path,
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--target",
        str(installed),
        str(wheels[0]),
    )

    script = """import json
import sys
from io import StringIO
from pathlib import Path

from pydantic import ValidationError

installed = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(installed))

import alphus
from alphus.config import load_config_stream
from alphus.execution.dispatch import run_rule
from alphus.execution.results import diagnostics_from_output
from alphus.plugins.builtin_registry import builtin_check_entry_points

selector = "morphology-extension-probe"
module = "alphus.gates.review.morphology_extension_probe"
assert Path(alphus.__file__).resolve().is_relative_to(installed)
entry_points = builtin_check_entry_points()
assert selector in entry_points
assert module not in sys.modules

try:
    load_config_stream(
        StringIO(
            "schema_version = 1\\n"
            "[checks.test_quality]\\n"
            "extensions = [\\".py\\"]\\n"
            "unrecognized = true\\n"
        )
    )
except ValidationError:
    strict_config_rejected = True
else:
    strict_config_rejected = False
assert strict_config_rejected

config = load_config_stream(
    StringIO(
        "schema_version = 1\\n"
        "[files]\\n"
        "include = [\\"src/**/*.py\\"]\\n"
        "[checks.test_quality]\\n"
        "extensions = [\\".py\\"]\\n"
    )
)
files = (root / "src/example.py",)
output = run_rule(selector, root, files, config)
diagnostics = diagnostics_from_output(selector, output)
assert module in sys.modules
assert len(diagnostics) == 1
assert diagnostics[0].rule_id == (
    "alphus/python/none/testing/morphology-extension-probe"
)
print(
    json.dumps(
        {
            "module_origin": str(Path(alphus.__file__).resolve()),
            "selected_entry_point": selector,
            "strict_config_rejected": strict_config_rejected,
            "diagnostic_id": diagnostics[0].rule_id,
        }
    )
)
"""
    report_text = _run(
        project,
        sys.executable,
        "-c",
        script,
        str(installed),
        str(project),
    )
    report = json.loads(report_text)
    assert Path(report["module_origin"]).is_relative_to(installed)
    assert report["selected_entry_point"] == _SELECTOR
    assert report["strict_config_rejected"] is True
    assert report["diagnostic_id"] == _RULE_ID

    entry_points = (project / ".registry-build" / "entry_points.txt").read_text(
        encoding="utf-8"
    )
    assert (
        "morphology-extension-probe = "
        "alphus.gates.review.morphology_extension_probe:ALPHUS_FEATURE"
    ) in entry_points
    assert all(
        (project / relative).read_bytes() == contents
        for relative, contents in generated_inputs.items()
    )
