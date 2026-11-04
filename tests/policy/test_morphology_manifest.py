"""Exercise deterministic, import-free morphology declaration discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.generate_morphology_manifest import main, render_manifest

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


def test_discovery_rejects_orphan_finding_complaint(tmp_path: Path) -> None:
    source = _DECLARATION
    _module(
        tmp_path,
        "demo",
        declaration=_with_field(source, "finding_tag_complaints", ("orphan",)),
    )

    with pytest.raises(
        ValueError, match="finding complaints are not declared by this feature"
    ):
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
        ValueError, match="finding complaints are not declared by this feature"
    ):
        render_manifest(tmp_path)


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
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_manifest(tmp_path), encoding="utf-8")

    assert main(["--root", str(tmp_path), "--check"]) == 0
    target.write_text(
        target.read_text(encoding="utf-8") + "# stale\n", encoding="utf-8"
    )
    assert main(["--root", str(tmp_path), "--check"]) == 1
    assert "is stale" in capsys.readouterr().err
