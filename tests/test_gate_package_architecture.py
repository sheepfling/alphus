"""Keep policy and shared support independent of gate execution."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import get_args

import pytest

from alphus.execution.dispatch import RULE_RUNNERS
from alphus.gates.hygiene.runners import HYGIENE_RULE_RUNNERS
from alphus.gates.markdown.runners import MARKDOWN_RULE_RUNNERS
from alphus.gates.repository.runners import REPOSITORY_RULE_RUNNERS
from alphus.gates.review import runners as review_runners
from alphus.gates.review.runners import REVIEW_RULE_RUNNERS
from alphus.gates.source.runners import SOURCE_RULE_RUNNERS
from alphus.gates.vcs.runners import VCS_RULE_RUNNERS
from alphus.policy.base import QualityRuleName


def test_shared_support_modules_do_not_import_gate_implementations() -> None:
    support = files("alphus.support")
    for source in support.iterdir():
        if not source.name.endswith(".py"):
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        ]
        imported.extend(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            name.startswith(("alphus.gates", "alphus.execution")) for name in imported
        ), source.name


def test_policy_models_do_not_import_execution_or_gate_packages() -> None:
    policy = files("alphus.policy")
    for source in policy.iterdir():
        if not source.name.endswith(".py"):
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        ]
        imported.extend(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            name.startswith(
                (
                    "alphus/python/none/correctness/cli-contract-violation",
                    "alphus.config",
                    "alphus.execution",
                    "alphus.gates",
                    "alphus.support",
                )
            )
            for name in imported
        ), source.name


def test_gate_themes_own_their_runner_mappings() -> None:
    themes = (
        (
            REVIEW_RULE_RUNNERS,
            {
                "numeric-literals",
                "repeated-numeric-limits",
                "typing-stub-suggestions",
                "prose-as-control",
                "rendered-value-reparsed",
                "positional-semantic-overrides",
                "unexplained-empty-results",
                "embedded-semantic-overrides",
                "heuristic-total-consumption",
                "provenance-as-ownership",
                "semantic-work-in-presentation",
                "parallel-normalization",
                "patch-cascade",
                "manual-matrix-kernels",
                "manual-elimination",
                "array-representation-churn",
                "cholesky-recurrence",
                "manual-quaternion-conjugation",
                "manual-quaternion-products",
                "manual-quaternion-normalization",
                "manual-quaternion-inversion",
                "manual-quaternion-vector-rotation",
                "manual-quaternion-matrix-conversion",
                "ecef-enu-transform",
                "ecef-ned-matrix-transform",
                "ned-basis-vectors",
                "scipy-constants",
                "test-quality",
                "input-contracts",
                "source-families",
                "source-test-coverage",
                "benchmark-docs",
                "positional-interfaces",
                "pydantic-practices",
                "fastapi-practices",
                "sqlalchemy-practices",
                "run-artifacts",
                "ci-workflows",
                "dynamic-markdown",
                "document-style",
                "suppression-reasons",
            },
        ),
        (
            SOURCE_RULE_RUNNERS,
            {
                "json-structure",
                "output-escaping",
                "path-discovery",
                "python-style",
                "runtime-types",
                "cli",
                "script-policy",
                "cyclomatic-complexity",
            },
        ),
        (
            REPOSITORY_RULE_RUNNERS,
            {
                "module-roles",
                "dependency-locks",
                "repository-layout",
                "documentation-config",
            },
        ),
        (
            VCS_RULE_RUNNERS,
            {"git-ignores", "git-attributes", "git-history"},
        ),
        (
            HYGIENE_RULE_RUNNERS,
            {"shared-utilities", "comment-markers"},
        ),
        (MARKDOWN_RULE_RUNNERS, {"markdown-shell-fences"}),
    )
    for runners, expected in themes:
        assert set(runners) == expected
        assert all(RULE_RUNNERS[name] is runner for name, runner in runners.items())
    assert RULE_RUNNERS["file-size"].__module__ == (
        "alphus.execution._generated_dispatch"
    )
    assert RULE_RUNNERS["package-boundaries"].__module__ == (
        "alphus.execution._generated_dispatch"
    )


def test_review_runner_registry_is_an_explicit_module_export() -> None:
    assert review_runners.__all__ == ["REVIEW_RULE_RUNNERS"]


def test_explicit_runner_adapters_cover_the_public_rule_catalog() -> None:
    assert set(RULE_RUNNERS) == set(get_args(QualityRuleName))


def _run_manifest_generator(
    repository: Path, fixture: Path, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    script = repository / "scripts" / "generate_runner_manifest.py"
    arguments = [sys.executable, str(script), "--root", str(fixture)]
    if check:
        arguments.append("--check")
    return subprocess.run(
        arguments,
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )


def _manifest_fixture(root: Path, selectors: Mapping[str, Sequence[str]]) -> None:
    base = root / "src" / "alphus" / "policy" / "base.py"
    base.parent.mkdir(parents=True)
    base.write_text(
        "from typing import Literal, TypeAlias\n"
        'QualityRuleName: TypeAlias = Literal["alpha", "beta"]\n',
        encoding="utf-8",
    )
    for theme, keys in selectors.items():
        runner = root / "src" / "alphus" / "gates" / theme / "runners.py"
        runner.parent.mkdir(parents=True, exist_ok=True)
        entries = ", ".join(f'"{key}": None' for key in keys)
        runner.write_text(
            "from types import MappingProxyType\n"
            f"{theme.upper()}_RULE_RUNNERS: object = "
            f"MappingProxyType({{{entries}}})\n",
            encoding="utf-8",
        )


def test_generated_runner_manifest_is_current(
    request: pytest.FixtureRequest,
) -> None:
    repository = Path(str(request.config.rootpath))
    result = _run_manifest_generator(repository, repository)
    assert result.returncode == 0, result.stderr


def test_manifest_generator_rejects_duplicate_selectors(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    repository = Path(str(request.config.rootpath))
    _manifest_fixture(tmp_path, {"alpha": ("alpha",), "beta": ("alpha",)})
    result = _run_manifest_generator(repository, tmp_path)
    assert result.returncode != 0
    assert "duplicate selector 'alpha'" in result.stderr


def test_manifest_generator_rejects_catalog_gaps(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    repository = Path(str(request.config.rootpath))
    _manifest_fixture(tmp_path, {"alpha": ("alpha",)})
    result = _run_manifest_generator(repository, tmp_path)
    assert result.returncode != 0
    assert "missing=['beta']" in result.stderr


def test_manifest_generation_is_sorted_and_check_detects_stale_output(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    repository = Path(str(request.config.rootpath))
    _manifest_fixture(tmp_path, {"zeta": ("beta",), "alpha": ("alpha",)})
    generated = _run_manifest_generator(repository, tmp_path, check=False)
    assert generated.returncode == 0, generated.stderr

    manifest_path = tmp_path / "src" / "alphus" / "execution" / "_generated_dispatch.py"
    manifest = manifest_path.read_text(encoding="utf-8")
    runner_imports = [
        line for line in manifest.splitlines() if line.startswith("from alphus.gates.")
    ]
    assert runner_imports == [
        "from alphus.gates.alpha.runners import ALPHA_RULE_RUNNERS",
        "from alphus.gates.zeta.runners import ZETA_RULE_RUNNERS",
    ]

    manifest_path.write_text(f"{manifest}# stale\n", encoding="utf-8")
    stale = _run_manifest_generator(repository, tmp_path)
    assert stale.returncode != 0
    assert "is stale" in stale.stderr


def test_root_contains_only_public_configuration_and_cli_boundaries() -> None:
    root = files("alphus")
    modules = {
        source.name
        for source in root.iterdir()
        if source.is_file() and source.name.endswith(".py")
    }
    assert modules == {"__init__.py", "__main__.py", "cli.py", "config.py"}


def test_target_audit_package_contains_only_python_310_helpers() -> None:
    root = files("alphus_stub_quality")
    modules = {source.name for source in root.iterdir() if source.is_file()}
    assert modules == {
        "__init__.py",
        "api_audit_support.py",
        "api_contracts.py",
        "runtime_audit.py",
        "py.typed",
    }
