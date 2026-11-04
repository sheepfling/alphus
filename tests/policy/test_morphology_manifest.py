"""Exercise deterministic, import-free morphology declaration discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.generate_morphology_manifest import main, render_manifest

_DECLARATION = {
    "selector": "demo-check",
    "finding_ids": ("alphus/repository/none/testing/demo-check",),
    "concern": "demo-concern",
    "claim": "A demo claim backed by a literal source finding.",
    "mechanisms": ("exact-rule",),
    "inspected_scope": ("repository-files",),
    "languages_formats": ("repository",),
    "evidence_kinds": ("path-line",),
    "evaluation_maturity": "synthetic-only",
}


def _repository(root: Path, *, selectors: tuple[str, ...] = ("demo-check",)) -> None:
    catalog = root / "src/alphus/policy/catalog.py"
    catalog.parent.mkdir(parents=True)
    entries = ", ".join(f"{selector!r}: None" for selector in selectors)
    catalog.write_text(
        "from types import MappingProxyType\n"
        f"_LEGACY_RULE_SPECS = MappingProxyType({{{entries}}})\n",
        encoding="utf-8",
    )


def _module(
    root: Path, name: str, *, declaration: dict[str, object] | None = None
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


def test_discovery_parses_literals_without_importing_feature_modules(
    tmp_path: Path,
) -> None:
    _repository(tmp_path)
    _module(tmp_path, "demo")

    manifest = render_manifest(tmp_path)

    assert "'demo-check': RuleMorphology(" in manifest
    assert "DetectionMechanism.EXACT_RULE" in manifest


def test_discovery_rejects_oversized_source_before_parsing(tmp_path: Path) -> None:
    _repository(tmp_path)
    _module(tmp_path, "demo")
    oversized = tmp_path / "src/alphus/gates/oversized.py"
    oversized.write_bytes(b"#" * (1_048_576 + 1))

    with pytest.raises(ValueError, match="byte scan limit"):
        render_manifest(tmp_path)


def test_discovery_rejects_duplicate_selectors(tmp_path: Path) -> None:
    _repository(tmp_path)
    _module(tmp_path, "alpha")
    _module(tmp_path, "beta")

    with pytest.raises(ValueError, match="duplicate morphology selector"):
        render_manifest(tmp_path)


def test_discovery_rejects_unknown_mechanisms(tmp_path: Path) -> None:
    _repository(tmp_path)
    declaration = {**_DECLARATION, "mechanisms": ("mystery",)}
    _module(tmp_path, "demo", declaration=declaration)

    with pytest.raises(ValueError, match="unsupported morphology mechanism"):
        render_manifest(tmp_path)


def test_checked_in_manifest_matches_feature_declarations() -> None:
    root = Path(__file__).resolve().parents[2]

    assert main(["--root", str(root), "--check"]) == 0


def test_check_detects_stale_generated_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repository(tmp_path)
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
