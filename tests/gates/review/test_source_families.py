from pathlib import Path

import pytest

from alphus.config import SourceFamilyPolicy
from alphus.gates.review import source_families
from alphus.gates.review.source_families import source_family_findings


def _write(root: Path, name: str, lines: int = 2) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join("pass" for _ in range(lines)), encoding="utf-8")
    return path.relative_to(root)


def test_groups_flat_python_family_as_lexical_only(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py", count)
        for name, count in (
            ("client", 3),
            ("server", 7),
            ("routes", 4),
            ("auth", 5),
            ("cache", 6),
        )
    ]
    independent = _write(tmp_path, "src/independent.py")

    findings = source_family_findings(
        tmp_path,
        [*paths, independent],
        SourceFamilyPolicy(
            min_family_files=5,
            file_length_limits=((".py", 500),),
        ),
    )

    assert len(findings) == 1
    assert findings[0].path == "src"
    assert findings[0].severity == "warning"
    assert "5 of 6 selected sibling source files" in findings[0].message
    assert "3–7" in findings[0].message
    assert "distribution:" in findings[0].message
    assert ".py≤500 lines" in findings[0].message
    assert "lexical-only, low-confidence" in findings[0].message
    assert "not assessed" in findings[0].message
    assert "Coupling" in findings[0].message
    assert "gateway_auth.py (5 lines)" in findings[0].message
    assert "min_family_files=5" in findings[0].message
    assert "min_prefix_characters=4" in findings[0].message
    assert "Scope includes" not in findings[0].message
    assert "include=**/*" in findings[0].message
    assert "exclude=**/vendor/**" in findings[0].message


def test_scope_exclusions_extensions_and_language_override_precedence(
    tmp_path: Path,
) -> None:
    names = ("client", "server", "routes", "auth", "cache")
    included = [_write(tmp_path, f"app/gateway_{name}.h") for name in names]
    excluded = [_write(tmp_path, f"app/tests/gateway_{name}.h") for name in names]
    generated = [_write(tmp_path, f"app/generated/gateway_{name}.h") for name in names]
    policy = SourceFamilyPolicy(
        include=("app/**",),
        exclude=("app/tests/**", "app/generated/**"),
        extensions=(".h",),
        language_overrides=((".h", "C"),),
        path_language_overrides=(("app/**", "C++"), ("app/c/**", "C")),
        min_family_files=5,
    )
    paths = [*included, *excluded, *generated]

    findings = source_family_findings(tmp_path, paths, policy)
    assert len(findings) == 1
    assert "5 of 5 selected sibling" in findings[0].message
    assert "language mix C++=5" in findings[0].message
    assert "last match wins" in findings[0].message
    assert "app/generated/gateway_" not in findings[0].message


@pytest.mark.parametrize(
    ("extension", "expected_language"),
    [
        (".py", "Python"),
        (".c", "C"),
        (".cpp", "C++"),
        (".js", "JavaScript"),
        (".ts", "TypeScript"),
    ],
)
def test_supports_python_c_cpp_and_javascript_families(
    tmp_path: Path, extension: str, expected_language: str
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}{extension}")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(extensions=(extension,), min_family_files=5),
    )
    assert len(findings) == 1
    assert f"language mix {expected_language}=5" in findings[0].message


@pytest.mark.parametrize(
    ("header_extension", "implementation_extension", "language_mix"),
    [(".h", ".c", "C=5, C/C++=5"), (".hpp", ".cpp", "C++=10")],
)
def test_pairs_c_cpp_headers_and_sources_but_keeps_physical_file_counts(
    tmp_path: Path,
    header_extension: str,
    implementation_extension: str,
    language_mix: str,
) -> None:
    paths = []
    for name in ("cache", "client", "config", "cursor", "codec"):
        paths.append(_write(tmp_path, f"src/gateway_{name}{header_extension}"))
        paths.append(_write(tmp_path, f"src/gateway_{name}{implementation_extension}"))

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            extensions=(header_extension, implementation_extension),
            min_family_files=5,
            file_length_limits=(
                (header_extension, 300),
                (implementation_extension, 500),
            ),
        ),
    )

    assert len(findings) == 1
    assert "5 logical units across 10 physical files" in findings[0].message
    assert "10 of 10 selected sibling source files" in findings[0].message
    assert f"language mix {language_mix}" in findings[0].message
    assert f"{implementation_extension}≤500 lines" in findings[0].message
    assert f"{header_extension}≤300 lines" in findings[0].message


def test_does_not_pair_same_stem_files_across_unrelated_languages(
    tmp_path: Path,
) -> None:
    paths = []
    for name in ("client", "server", "routes", "auth", "cache"):
        paths.append(_write(tmp_path, f"src/gateway_{name}.py"))
        paths.append(_write(tmp_path, f"src/gateway_{name}.ts"))
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(extensions=(".py", ".ts"), min_family_files=5),
    )
    assert len(findings) == 1
    assert "10 logical units across 10 physical files" in findings[0].message
    assert "language mix Python=5, TypeScript=5" in findings[0].message


def test_nested_prefixes_are_partitioned_without_duplicate_members(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_admin_{name}.py")
        for name in ("create", "delete", "load", "save", "update")
    ] + [
        _write(tmp_path, f"src/gateway_client_{name}.py")
        for name in ("create", "delete", "load", "save", "update")
    ]
    findings = source_family_findings(
        tmp_path, paths, SourceFamilyPolicy(min_family_files=5)
    )
    assert len(findings) == 2
    assert "Family gateway_admin_*" in findings[0].message
    assert "Family gateway_client_*" in findings[1].message
    assert all("gateway_*" not in finding.message for finding in findings)


def test_prefix_minimum_and_family_threshold_are_configurable(tmp_path: Path) -> None:
    short_prefix = [
        _write(tmp_path, f"src/api{number}_client.py") for number in range(5)
    ]
    too_few = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth")
    ]
    assert (
        source_family_findings(
            tmp_path,
            [*short_prefix, *too_few],
            SourceFamilyPolicy(min_family_files=5, min_prefix_characters=4),
        )
        == []
    )

    findings = source_family_findings(
        tmp_path,
        too_few,
        SourceFamilyPolicy(min_family_files=4, min_prefix_characters=4),
    )
    assert len(findings) == 1


def test_empty_inventory_has_no_findings(tmp_path: Path) -> None:
    assert source_family_findings(tmp_path, [], SourceFamilyPolicy()) == []


def test_input_order_does_not_change_grouping_or_serialized_findings(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py", lines)
        for name, lines in (
            ("client", 3),
            ("server", 7),
            ("routes", 4),
            ("auth", 5),
            ("cache", 6),
        )
    ]
    policy = SourceFamilyPolicy(min_family_files=5)
    forward = source_family_findings(tmp_path, paths, policy)
    reverse = source_family_findings(tmp_path, reversed(paths), policy)
    assert forward == reverse


def test_inventory_is_bounded_and_partial_results_are_marked(tmp_path: Path) -> None:
    paths = [_write(tmp_path, f"src/group_{index}.py") for index in range(5)]
    limited = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(min_family_files=2, max_files=2),
    )
    assert len(limited) == 1
    assert "scan incomplete" in limited[0].message
    assert "no clean result can be inferred" in limited[0].message


def test_member_evidence_is_bounded_and_explicitly_truncated(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_member_{index}.py", index + 1)
        for index in range(5)
    ]
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(min_family_files=5, max_reported_members=2),
    )
    assert len(findings) == 1
    assert "Members (showing 2 of 5)" in findings[0].message
    assert "member evidence truncated" in findings[0].message


def test_output_limit_is_explicit(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/{group}_{member}.py")
        for group in ("alpha", "bravo", "charlie")
        for member in ("one", "two", "three", "four", "five")
    ]
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(min_family_files=5, max_findings=1),
    )
    assert len(findings) == 1
    assert "output truncated" in findings[0].message


def test_unreadable_source_remains_in_lexical_candidate_and_marks_scan_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    unreadable = paths[-1]

    def fail_read(path: Path) -> int:
        if path.name == unreadable.name:
            raise OSError("synthetic read failure")
        return 2

    monkeypatch.setattr(source_families, "_line_count", fail_read)
    findings = source_family_findings(tmp_path, paths, SourceFamilyPolicy())
    assert len(findings) == 2
    assert any("scan incomplete" in finding.message for finding in findings)
    candidate = next(
        finding for finding in findings if "Family gateway_*" in finding.message
    )
    assert "5 logical units across 5 physical files" in candidate.message
    assert "1 unavailable" in candidate.message
    assert "line count unavailable" in candidate.message


def test_rejects_invalid_source_family_policy() -> None:
    with pytest.raises(ValueError):
        SourceFamilyPolicy(min_family_files=0)
    with pytest.raises(ValueError):
        SourceFamilyPolicy(max_files=0)
    with pytest.raises(ValueError):
        SourceFamilyPolicy(max_reported_members=0)
    with pytest.raises(ValueError):
        SourceFamilyPolicy(extensions=(".py", ".py"))
    with pytest.raises(ValueError):
        SourceFamilyPolicy(exclude=("../private/**",))
    with pytest.raises(ValueError):
        SourceFamilyPolicy(file_length_limits=((".py", 0),))
    with pytest.raises(ValueError):
        SourceFamilyPolicy(language_overrides=((".py", "Python"), (".py", "Py")))
    with pytest.raises(ValueError):
        SourceFamilyPolicy(language_overrides=(("not-an-extension", "Py"),))
    with pytest.raises(ValueError):
        SourceFamilyPolicy(path_language_overrides=(("../outside/**", "C"),))
    with pytest.raises(ValueError):
        SourceFamilyPolicy(max_scope_patterns=1)
