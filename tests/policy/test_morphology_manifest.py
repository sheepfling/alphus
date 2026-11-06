"""Exercise deterministic, import-free morphology declaration discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.generate_morphology_manifest import (
    feature_registrations,
    main,
    render_feature_manifest,
    render_manifest,
)
from scripts.generate_runner_manifest import render_manifest as render_runner_manifest

_DECLARATION: tuple[tuple[str, object], ...] = (
    ("selector", "demo-check"),
    ("finding_tag_complaints", ("demo-check",)),
    ("concern", "demo-concern"),
    ("claim_kind", "condition"),
    ("claim", "A demo claim backed by a literal source finding."),
    ("mechanisms", ("exact-rule",)),
    ("inspected_scope", ("repository-files",)),
    ("languages_formats", ("repository",)),
    ("evidence_kinds", ("path-line",)),
    ("evaluation_maturity", "synthetic-only"),
)


def _with_field(
    declaration: tuple[tuple[str, object], ...], key: str, value: object
) -> tuple[tuple[str, object], ...]:
    return tuple((name, value if name == key else item) for name, item in declaration)


def _module(
    root: Path, name: str, *, declaration: tuple[tuple[str, object], ...] | None = None
) -> None:
    path = root / f"src/alphus/gates/{name}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    value = declaration or _DECLARATION
    path.write_text(
        "raise RuntimeError('feature code must not be imported')\n"
        f"ALPHUS_MORPHOLOGY = {value!r}\n"
        "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'demo-check')\n",
        encoding="utf-8",
    )


def test_feature_owned_discovery_accepts_selector_without_central_registry(
    tmp_path: Path,
) -> None:
    _module(tmp_path, "demo")

    manifest = render_manifest(tmp_path)

    assert '"demo-check": RuleMorphology(' in manifest
    assert "DetectionMechanism.EXACT_RULE" in manifest
    assert "ClaimKind.CONDITION" in manifest
    assert "RuleTag(" in manifest
    assert "Scope.REPOSITORY" in manifest
    assert "Framework.NONE" in manifest
    assert "Category.TESTING" in manifest


def test_feature_definition_generates_catalog_and_lazy_runner_views(
    tmp_path: Path,
) -> None:
    gates = tmp_path / "src/alphus/gates"
    gates.mkdir(parents=True)
    feature_declaration = _DECLARATION + (
        ("policy_field", "demo_policy"),
        ("output_shape", "findings"),
        ("summary", "Reports a demo condition."),
        ("applies_to", ("python",)),
        ("domains", ()),
        ("requires_files", True),
        ("runner_module", "alphus.gates.demo_check"),
        ("runner_name", "check_demo"),
    )
    (gates / "demo_check.py").write_text(
        "ALPHUS_CHECK = "
        f"{feature_declaration!r}\n"
        "def check_demo(root, files, config):\n    return []\n"
        "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'demo-check')\n",
        encoding="utf-8",
    )
    policy = tmp_path / "src/alphus/policy"
    policy.mkdir(parents=True)
    (policy / "orchestration.py").write_text(
        "class CheckPolicies:\n    demo_policy: object | None = None\n",
        encoding="utf-8",
    )
    (policy / "base.py").write_text(
        "from typing import Literal, TypeAlias\n"
        'QualityRuleName: TypeAlias = Literal["demo-check"]\n',
        encoding="utf-8",
    )
    group = gates / "demo_group"
    group.mkdir()
    (group / "runners.py").write_text(
        "from types import MappingProxyType\n"
        "DEMO_GROUP_RULE_RUNNERS: object = MappingProxyType({})\n",
        encoding="utf-8",
    )

    registration = feature_registrations(tmp_path)
    definitions = render_feature_manifest(tmp_path)
    runner_manifest = render_runner_manifest(tmp_path)

    assert [item.selector for item in registration] == ["demo-check"]
    assert '"demo-check": FeatureDefinition(' in definitions
    assert "def _run_feature_demo_check(" in runner_manifest
    assert 'import_module("alphus.gates.demo_check")' in runner_manifest
    assert "runner = cast(_RuleRunner, module.check_demo)" in runner_manifest
    assert '"demo-check": _run_feature_demo_check' in runner_manifest


def test_discovery_rejects_orphan_finding_complaint(tmp_path: Path) -> None:
    source = _DECLARATION
    _module(
        tmp_path,
        "demo",
        declaration=_with_field(source, "finding_tag_complaints", ("orphan",)),
    )

    with pytest.raises(ValueError, match="finding complaint 'orphan' is not declared"):
        render_manifest(tmp_path)


def test_discovery_ignores_rule_tags_with_dynamic_components(tmp_path: Path) -> None:
    _module(tmp_path, "demo")
    path = tmp_path / "src/alphus/gates/demo.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'demo-check')",
            "rule_tag(scope, Framework.NONE, Category.TESTING, 'demo-check')",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match="finding complaint 'demo-check' is not declared"
    ):
        render_manifest(tmp_path)


def test_discovery_rejects_orphan_before_duplicate_complaint_matches(
    tmp_path: Path,
) -> None:
    declaration = _with_field(
        _DECLARATION, "finding_tag_complaints", ("orphan", "shared")
    )
    _module(tmp_path, "demo", declaration=declaration)
    path = tmp_path / "src/alphus/gates/demo.py"
    with path.open("a", encoding="utf-8") as source:
        source.write(
            "rule_tag(Scope.PYTHON, Framework.NONE, Category.TESTING, 'shared')\n"
            "rule_tag(Scope.MARKDOWN, Framework.NONE, Category.TESTING, 'shared')\n"
        )

    with pytest.raises(ValueError, match="finding complaint 'orphan' is not declared"):
        render_manifest(tmp_path)


def test_discovery_rejects_ambiguous_complaint_matches(tmp_path: Path) -> None:
    declaration = _with_field(_DECLARATION, "finding_tag_complaints", ("shared",))
    _module(tmp_path, "demo", declaration=declaration)
    path = tmp_path / "src/alphus/gates/demo.py"
    with path.open("a", encoding="utf-8") as source:
        source.write(
            "rule_tag(Scope.PYTHON, Framework.NONE, Category.TESTING, 'shared')\n"
            "rule_tag(Scope.MARKDOWN, Framework.NONE, Category.TESTING, 'shared')\n"
        )

    with pytest.raises(
        ValueError, match="finding complaint 'shared' resolves to multiple rule tags"
    ):
        render_manifest(tmp_path)


def test_discovery_preserves_declared_complaint_order(tmp_path: Path) -> None:
    declaration = _with_field(
        _DECLARATION, "finding_tag_complaints", ("second", "demo-check")
    )
    _module(tmp_path, "demo", declaration=declaration)
    path = tmp_path / "src/alphus/gates/demo.py"
    with path.open("a", encoding="utf-8") as source:
        source.write(
            "rule_tag(Scope.PYTHON, Framework.NONE, Category.TESTING, 'second')\n"
        )

    manifest = render_manifest(tmp_path)
    finding_ids = manifest.split("finding_ids=(", maxsplit=1)[1]

    assert finding_ids.index('"second"') < finding_ids.index('"demo-check"')


def test_discovery_rejects_oversized_source_before_parsing(tmp_path: Path) -> None:
    _module(tmp_path, "demo")
    oversized = tmp_path / "src/alphus/gates/oversized.py"
    oversized.write_bytes(b"#" * (1_048_576 + 1))

    with pytest.raises(ValueError, match="byte scan limit"):
        render_manifest(tmp_path)


def test_discovery_rejects_duplicate_selectors(tmp_path: Path) -> None:
    _module(tmp_path, "alpha")
    _module(tmp_path, "beta")

    with pytest.raises(ValueError, match="duplicate morphology selector"):
        render_manifest(tmp_path)


def test_discovery_rejects_duplicate_finding_ids_across_selectors(
    tmp_path: Path,
) -> None:
    _module(tmp_path, "alpha")
    declaration = _with_field(_DECLARATION, "selector", "other-check")
    _module(tmp_path, "beta", declaration=declaration)

    with pytest.raises(
        ValueError, match="finding ID .* declared by multiple selectors"
    ):
        render_manifest(tmp_path)


def test_discovery_rejects_non_slug_morphology_values(tmp_path: Path) -> None:
    declaration = _with_field(_DECLARATION, "languages_formats", ("Python",))
    _module(tmp_path, "bad_slug", declaration=declaration)

    with pytest.raises(
        ValueError, match="languages_formats must contain lowercase slugs"
    ):
        render_manifest(tmp_path)


def test_discovery_rejects_symlinked_python_modules(tmp_path: Path) -> None:
    _module(tmp_path, "local")
    outside = tmp_path / "outside.py"
    outside.write_text("ALPHUS_MORPHOLOGY = {}\n", encoding="utf-8")
    (tmp_path / "src/alphus/gates/external.py").symlink_to(outside)

    with pytest.raises(ValueError, match="escapes the built-in gates root"):
        render_manifest(tmp_path)


def test_discovery_rejects_symlinked_gates_root(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "demo.py").write_text("ALPHUS_MORPHOLOGY = ()\n", encoding="utf-8")
    gates = repository / "src/alphus/gates"
    gates.parent.mkdir(parents=True)
    gates.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="built-in gates root escapes the repository"):
        render_manifest(repository)


def test_discovery_rejects_unknown_mechanisms(tmp_path: Path) -> None:
    declaration = _with_field(_DECLARATION, "mechanisms", ("mystery",))
    _module(tmp_path, "demo", declaration=declaration)

    with pytest.raises(ValueError, match="unsupported morphology mechanism"):
        render_manifest(tmp_path)


def test_checked_in_manifest_matches_feature_declarations(
    pytestconfig: pytest.Config,
) -> None:
    assert main(["--root", str(pytestconfig.rootpath), "--check"]) == 0


def test_check_detects_stale_generated_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _module(tmp_path, "demo")
    target = tmp_path / "src/alphus/policy/_generated_morphology.py"
    feature_target = tmp_path / "src/alphus/policy/_generated_feature_definitions.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_manifest(tmp_path), encoding="utf-8")
    feature_target.write_text(render_feature_manifest(tmp_path), encoding="utf-8")

    assert main(["--root", str(tmp_path), "--check"]) == 0
    target.write_text(
        target.read_text(encoding="utf-8") + "# stale\n", encoding="utf-8"
    )
    assert main(["--root", str(tmp_path), "--check"]) == 1
    assert "is stale" in capsys.readouterr().err
