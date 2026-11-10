"""Prove independent same-selector complaint contributions end to end."""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from alphus.execution.processes import run_captured_process
from alphus.support.git import run_git
from scripts.generate_morphology_manifest import complaint_contributions


@dataclass(frozen=True, slots=True)
class _ContributionCase:
    key: str
    policy_file: str
    policy_module: str
    module: str
    policy_field: str
    complaint: str
    marker: str
    summary: str


_CONTRIBUTIONS = (
    _ContributionCase(
        "literal_assertion",
        "literal_assertion_policy.py",
        "literal_assertion_policy",
        "literal_assertion",
        "test_quality_literal_assertion",
        "literal-assertion-marker",
        "LITERAL_ASSERTION_MARKER",
        "Reports an explicit literal assertion acceptance marker.",
    ),
    _ContributionCase(
        "shared_oracle",
        "shared_oracle_policy.py",
        "shared_oracle_policy",
        "shared_oracle",
        "test_quality_shared_oracle_probe",
        "shared-oracle-probe-marker",
        "SHARED_ORACLE_PROBE_MARKER",
        "Reports an explicit shared oracle acceptance marker.",
    ),
)


def _contribution_case(key: str) -> _ContributionCase:
    for contribution in _CONTRIBUTIONS:
        if contribution.key == key:
            return contribution
    raise ValueError(f"unknown acceptance contribution {key!r}")


def _copy_project(source: Path, target: Path) -> None:
    for name in ("pyproject.toml", "build_backend.py", "README.md"):
        shutil.copy2(source / name, target / name)
    for name in ("src", "scripts"):
        shutil.copytree(
            source / name,
            target / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )


def _run(root: Path, *arguments: str, timeout: int = 300) -> str:
    result = run_captured_process(arguments, root, timeout=timeout)
    assert result.returncode == 0, (
        f"command failed: {arguments!r}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result.stdout


def _git(root: Path, *arguments: str, expected: int = 0) -> str:
    result = run_git(root, *arguments)
    assert result.returncode == expected, result.stderr.decode(
        "utf-8", errors="replace"
    )
    return result.stdout.decode("utf-8", errors="replace")


def _write_contribution(root: Path, key: str) -> tuple[Path, ...]:
    declaration = _contribution_case(key)
    policy_module = declaration.module
    policy_model_module = declaration.policy_module
    field = declaration.policy_field
    complaint = declaration.complaint
    summary = declaration.summary
    policy_path = root / "src/alphus/policy" / declaration.policy_file
    policy_path.write_text(
        "from alphus.policy.base import StrictModel\n\n\n"
        "class ContributionPolicy(StrictModel):\n"
        "    marker: str\n",
        encoding="utf-8",
    )
    module_path = root / "src/alphus/gates/review/contributions" / f"{policy_module}.py"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(
        f'''"""One independently owned test-quality complaint provider."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.plugins.complaints import (
    ComplaintContribution,
    ComplaintContributionDefinition,
)
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.{policy_model_module} import ContributionPolicy

ALPHUS_COMPLAINT_DEFINITION: Final = ComplaintContributionDefinition(
    selector="test-quality",
    policy_field="{field}",
    policy_model=ContributionPolicy,
    morphology=RuleMorphology(
        selector="test-quality",
        finding_ids=(
            RuleTag(
                Scope.PYTHON,
                Framework.NONE,
                Category.TESTING,
                "{complaint}",
            ),
        ),
        concern="test-evidence-quality",
        claim_kind=ClaimKind.CONDITION,
        claim="Reports the explicit acceptance marker when it is present.",
        mechanisms=(DetectionMechanism.EXACT_RULE,),
        inspected_scope=("selected-test-files",),
        languages_formats=("python",),
        evidence_kinds=("source-marker", "source-location"),
        evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
    ),
    summary="{summary}",
)


def _run(
    root: Path, files: Sequence[Path], policy: ContributionPolicy
) -> list[Finding]:
    findings: list[Finding] = []
    for relative in files:
        source = (root / relative).read_text(encoding="utf-8")
        if policy.marker in source:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.PYTHON,
                        Framework.NONE,
                        Category.TESTING,
                        "{complaint}",
                    ),
                    path=relative.as_posix(),
                    line=1,
                    message="acceptance marker found",
                )
            )
    return findings


ALPHUS_CONTRIBUTION: Final = ComplaintContribution(
    definition=ALPHUS_COMPLAINT_DEFINITION,
    runner=_run,
)
''',
        encoding="utf-8",
    )
    test_path = root / f"tests/gates/review/contributions/test_{policy_module}.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(
        f"def test_{policy_module}_has_stable_complaint_identity() -> None:\n"
        f'    assert "{complaint}" in "{module_path.read_text(encoding="utf-8")}"\n',
        encoding="utf-8",
    )
    doc_path = root / f"docs/contributions/test_quality/{policy_module}.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(f"# {policy_module.replace('_', ' ').title()}\n\n{summary}\n")
    return policy_path, module_path, test_path, doc_path


def _make_base(source: Path, target: Path) -> str:
    target.mkdir()
    _copy_project(source, target)
    _git(target, "init", "--quiet", "--initial-branch=main")
    _git(target, "config", "user.name", "Alphus Acceptance")
    _git(target, "config", "user.email", "alphus@example.invalid")
    _git(target, "add", "pyproject.toml", "build_backend.py", "README.md")
    _git(target, "add", "src", "scripts")
    _git(target, "commit", "--quiet", "-m", "production morphology baseline")
    return _git(target, "rev-parse", "HEAD").strip()


def _add_branch_contribution(root: Path, key: str, branch: str) -> tuple[str, ...]:
    _git(root, "switch", "-c", branch)
    paths = _write_contribution(root, key)
    relative = tuple(path.relative_to(root).as_posix() for path in paths)
    _git(root, "add", *relative)
    _git(root, "commit", "--quiet", "-m", f"add {key} complaint contribution")
    return relative


def _make_branches(source: Path, target: Path) -> tuple[str, str, str]:
    base = _make_base(source, target)
    literal_paths = _add_branch_contribution(
        target, "literal_assertion", "complaint/literal"
    )
    _git(target, "switch", "--quiet", "main")
    oracle_paths = _add_branch_contribution(target, "shared_oracle", "complaint/oracle")
    assert set(literal_paths).isdisjoint(oracle_paths)
    literal = _git(target, "rev-parse", "complaint/literal").strip()
    oracle = _git(target, "rev-parse", "complaint/oracle").strip()
    assert literal != base and oracle != base
    return base, literal, oracle


def _merge_order(source: Path, target: Path, order: tuple[str, str]) -> tuple[str, ...]:
    _make_branches(source, target)
    base_branch = order[0]
    other_branch = order[1]
    _git(target, "switch", "--quiet", base_branch)
    merge = run_git(target, "merge", "--no-edit", other_branch)
    assert merge.returncode == 0, merge.stderr.decode("utf-8", errors="replace")
    assert not tuple((target / "src/alphus/gates/review/contributions").glob("*.py~"))
    _run(
        target,
        sys.executable,
        "-m",
        "scripts.generate_morphology_manifest",
        "--root",
        str(target),
    )
    _run(
        target,
        sys.executable,
        "-m",
        "scripts.generate_runner_manifest",
        "--root",
        str(target),
    )
    return tuple(
        (target / relative).read_text(encoding="utf-8")
        for relative in (
            "src/alphus/policy/_generated_feature_policies.py",
            "src/alphus/policy/_generated_morphology.py",
        )
    )


def test_independent_same_aggregate_contributions_merge_both_ways_and_run_from_wheel(
    pytestconfig: pytest.Config,
    tmp_path: Path,
) -> None:
    source = Path(pytestconfig.rootpath)
    left_project = tmp_path / "left"
    right_project = tmp_path / "right"
    left = _merge_order(source, left_project, ("complaint/literal", "complaint/oracle"))
    right = _merge_order(
        source, right_project, ("complaint/oracle", "complaint/literal")
    )
    assert left == right
    assert all(item.policy_field in left[0] for item in _CONTRIBUTIONS)
    assert "COMPLAINT_MORPHOLOGY_BY_POLICY_FIELD" in left[1]
    assert all(item.policy_field in left[1] for item in _CONTRIBUTIONS)

    for declaration in _CONTRIBUTIONS:
        assert (
            left_project
            / "tests/gates/review/contributions"
            / f"test_{declaration.module}.py"
        ).is_file()
        assert (
            left_project
            / "docs/contributions/test_quality"
            / f"{declaration.module}.md"
        ).is_file()

    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _run(
        left_project,
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-build-isolation",
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
    input_file = left_project / "tests/acceptance.py"
    input_file.parent.mkdir(parents=True, exist_ok=True)
    input_file.write_text(
        "# LITERAL_ASSERTION_MARKER\n# SHARED_ORACLE_PROBE_MARKER\n",
        encoding="utf-8",
    )
    script = '''
import json
import sys
from io import StringIO
from pathlib import Path
from pydantic import ValidationError

installed = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(installed))
from alphus.config import load_config_stream
from alphus.execution.dispatch import run_rule
from alphus.execution.results import diagnostics_from_output
from alphus.plugins.complaint_registry import complaint_contribution_entry_points

try:
    load_config_stream(StringIO("""schema_version = 1
[checks.test_quality]
extensions = [".py"]
[checks.test_quality_literal_assertion]
marker = "LITERAL_ASSERTION_MARKER"
[checks.test_quality_shared_oracle_probe]
marker = "SHARED_ORACLE_PROBE_MARKER"
unknown = true
"""))
except ValidationError:
    invalid_rejected = True
else:
    invalid_rejected = False
assert invalid_rejected
config = load_config_stream(StringIO("""schema_version = 1
[checks.test_quality]
extensions = [".py"]
[checks.test_quality_literal_assertion]
marker = "LITERAL_ASSERTION_MARKER"
[checks.test_quality_shared_oracle_probe]
marker = "SHARED_ORACLE_PROBE_MARKER"
"""))
points = complaint_contribution_entry_points("test-quality")
assert set(points) == {
    "test_quality_literal_assertion",
    "test_quality_shared_oracle_probe",
}
assert "alphus.gates.review.contributions.literal_assertion" not in sys.modules
assert "alphus.gates.review.contributions.shared_oracle" not in sys.modules
single = load_config_stream(StringIO("""schema_version = 1
[checks.test_quality]
extensions = [".py"]
[checks.test_quality_literal_assertion]
marker = "LITERAL_ASSERTION_MARKER"
"""))
single_output = run_rule(
    "test-quality", root, (Path("tests/acceptance.py"),), single
)
assert type(single.checks.test_quality_literal_assertion) is points[
    "test_quality_literal_assertion"
].load().definition.policy_model
single_ids = {
    item.rule_id for item in diagnostics_from_output("test-quality", single_output)
}
assert single_ids == {"alphus/python/none/testing/literal-assertion-marker"}
assert "alphus.gates.review.contributions.literal_assertion" in sys.modules
assert "alphus.gates.review.contributions.shared_oracle" not in sys.modules
output = run_rule("test-quality", root, (Path("tests/acceptance.py"),), config)
assert type(config.checks.test_quality_literal_assertion) is points[
    "test_quality_literal_assertion"
].load().definition.policy_model
assert type(config.checks.test_quality_shared_oracle_probe) is points[
    "test_quality_shared_oracle_probe"
].load().definition.policy_model
diagnostics = diagnostics_from_output("test-quality", output)
ids = {item.rule_id for item in diagnostics}
ordered_ids = [item.rule_id for item in diagnostics]
assert ids == {
    "alphus/python/none/testing/literal-assertion-marker",
    "alphus/python/none/testing/shared-oracle-probe-marker",
}
assert ordered_ids == sorted(ids)
for provider in (
    "alphus.gates.review.contributions.literal_assertion",
    "alphus.gates.review.contributions.shared_oracle",
):
    assert Path(sys.modules[provider].__file__).resolve().is_relative_to(installed)
print(
    json.dumps(
        {
            "ids": sorted(ids),
            "installed_origin": str(Path(sys.modules["alphus"].__file__).resolve()),
        }
    )
)
'''
    report = json.loads(
        _run(
            left_project,
            sys.executable,
            "-c",
            script,
            str(installed),
            str(left_project),
        )
    )
    assert Path(report["installed_origin"]).is_relative_to(installed)
    assert report["ids"] == sorted(
        "alphus/python/none/testing/" + item.complaint for item in _CONTRIBUTIONS
    )


def test_same_aggregate_duplicate_complaint_identity_is_rejected(
    pytestconfig: pytest.Config,
    tmp_path: Path,
) -> None:
    source = Path(pytestconfig.rootpath)
    project = tmp_path / "project"
    project.mkdir()
    _copy_project(source, project)
    _write_contribution(project, "literal_assertion")
    _write_contribution(project, "shared_oracle")
    second = project / "src/alphus/gates/review/contributions/shared_oracle.py"
    source_text = second.read_text(encoding="utf-8")
    second.write_text(
        source_text.replace("shared-oracle-probe-marker", "literal-assertion-marker"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate complaint finding ID"):
        complaint_contributions(project)


def test_same_aggregate_duplicate_policy_fragment_is_rejected(
    pytestconfig: pytest.Config,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _copy_project(Path(pytestconfig.rootpath), project)
    _write_contribution(project, "literal_assertion")
    _write_contribution(project, "shared_oracle")
    second = project / "src/alphus/gates/review/contributions/shared_oracle.py"
    source_text = second.read_text(encoding="utf-8")
    second.write_text(
        source_text.replace(
            "test_quality_shared_oracle_probe",
            "test_quality_literal_assertion",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate complaint policy field"):
        complaint_contributions(project)
