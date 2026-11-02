from collections.abc import Callable
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
    assert "move" not in findings[0].message
    assert "gateway_auth.py (5 lines)" in findings[0].message
    assert "min_family_files=5" in findings[0].message
    assert "min_prefix_characters=4" in findings[0].message
    assert "Scope includes" not in findings[0].message
    assert "include=**/*" in findings[0].message
    assert "exclude=**/vendor/**" in findings[0].message


def test_opt_in_python_import_evidence_reports_resolved_edges(tmp_path: Path) -> None:
    paths = []
    for name in ("client", "server", "routes", "auth", "cache"):
        paths.append(
            _write(
                tmp_path,
                f"src/gateway_{name}.py",
                1,
            )
        )
    (tmp_path / "src/gateway_client.py").write_text(
        "from gateway_server import serve\n", encoding="utf-8"
    )
    (tmp_path / "src/gateway_server.py").write_text(
        "from gateway_client import connect\n", encoding="utf-8"
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    assert len(findings) == 1
    assert "2 resolved edge(s) target another family member" in findings[0].message
    assert "src/gateway_client.py:1 → src/gateway_server.py" in findings[0].message
    assert "Direct imports are partial evidence only" in findings[0].message


def test_import_evidence_requires_explicit_module_root() -> None:
    with pytest.raises(ValueError, match="requires explicit python_module_roots"):
        SourceFamilyPolicy(python_import_evidence=True)


def test_import_parse_failure_is_reported_as_incomplete(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    (tmp_path / "src/gateway_client.py").write_text("def broken(:\n", encoding="utf-8")

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    assert any("could not be analyzed" in finding.message for finding in findings)
    assert any("no clean result can be inferred" in finding.message for finding in findings)


def test_scope_exclusions_extensions_and_language_override_precedence(
    tmp_path: Path,
) -> None:
    names = ("client", "server", "routes", "auth", "cache")
    included = [_write(tmp_path, f"app/gateway_{name}.h") for name in names]
    path_overridden = [_write(tmp_path, f"app/c/gateway_{name}.h") for name in names]
    excluded = [
        _write(tmp_path, f"app/{directory}/gateway_{name}.h")
        for directory in (
            "tests",
            "generated",
            "fixtures",
            "compat",
            "vendor",
            "schema",
        )
        for name in names
    ]
    policy = SourceFamilyPolicy(
        include=("app/**",),
        exclude=(
            "app/tests/**",
            "app/generated/**",
            "app/fixtures/**",
            "app/compat/**",
            "app/vendor/**",
            "app/schema/**",
        ),
        extensions=(".h",),
        language_overrides=((".h", "C"),),
        path_language_overrides=(("app/**", "C++"), ("app/c/**", "C")),
        min_family_files=5,
    )
    paths = [*included, *path_overridden, *excluded]

    findings = source_family_findings(tmp_path, paths, policy)
    assert len(findings) == 2
    assert "language mix C++=5" in findings[0].message
    assert "language mix C=5" in findings[1].message
    assert all("5 of 5 selected sibling" in finding.message for finding in findings)
    assert all("last match wins" in finding.message for finding in findings)
    assert all("app/generated/gateway_" not in finding.message for finding in findings)
    assert all("app/compat/gateway_" not in finding.message for finding in findings)


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


def test_case_sensitive_stems_do_not_create_false_header_source_pairs(
    tmp_path: Path,
) -> None:
    paths = []
    for name in ("cache", "client", "config", "cursor", "codec"):
        paths.append(_write(tmp_path, f"src/gateway_{name}.h"))
        paths.append(_write(tmp_path, f"src/gateway_{name}.c"))
    paths.extend(
        [
            _write(tmp_path, "src/gateway_Legacy.h"),
            _write(tmp_path, "src/gateway_legacy.c"),
        ]
    )
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(extensions=(".h", ".c"), min_family_files=5),
    )
    assert len(findings) == 1
    assert "7 logical units across 12 physical files" in findings[0].message


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


def test_tokenization_and_directory_boundaries_are_explicit(tmp_path: Path) -> None:
    root_family = [
        _write(tmp_path, f"src/{name}.py")
        for name in (
            "GatewayClient",
            "gateway_server",
            "gateway-routes",
            "gateway.auth",
            "gatewayCache",
        )
    ]
    nested_family = [
        _write(tmp_path, f"src/impl/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    findings = source_family_findings(
        tmp_path,
        [*root_family, *nested_family],
        SourceFamilyPolicy(min_family_files=5),
    )
    assert [
        (finding.path, "Family gateway_*" in finding.message) for finding in findings
    ] == [
        ("src", True),
        ("src/impl", True),
    ]


def test_prefix_minimum_and_family_threshold_are_configurable(tmp_path: Path) -> None:
    short_prefix = [
        _write(tmp_path, f"src/api_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    too_few = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth")
    ]
    assert (
        source_family_findings(
            tmp_path,
            short_prefix,
            SourceFamilyPolicy(min_family_files=5, min_prefix_characters=4),
        )
        == []
    )
    assert (
        len(
            source_family_findings(
                tmp_path,
                short_prefix,
                SourceFamilyPolicy(min_family_files=5, min_prefix_characters=3),
            )
        )
        == 1
    )
    assert (
        source_family_findings(
            tmp_path,
            too_few,
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


def test_line_count_handles_newline_variants_and_chunk_boundaries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "newlines.py"
    path.write_bytes(("a" * 65_535 + "\r\nb\rc\n" + "d\u2028e").encode("utf-8"))
    assert source_families._line_count(path) == 5


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


def test_large_inventory_is_bounded_and_partial_results_are_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("auth", "cache", "client", "routes", "server")
    ]
    paths.extend(Path(f"src/zfamily_{index}_client.py") for index in range(10_000))
    reads: list[Path] = []
    line_count = source_families._line_count

    def track_read(path: Path) -> int:
        reads.append(path)
        return line_count(path)

    monkeypatch.setattr(source_families, "_line_count", track_read)
    limited = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(min_family_files=2, max_files=2),
    )
    assert len(limited) == 2
    assert len(reads) == 2
    assert any("scan incomplete" in finding.message for finding in limited)
    assert any(
        "no clean result can be inferred" in finding.message for finding in limited
    )


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

    partial_paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    partial_paths.append(_write(tmp_path, "src/independent.py"))
    partial = source_family_findings(
        tmp_path,
        partial_paths,
        SourceFamilyPolicy(min_family_files=5, max_files=5, max_findings=1),
    )
    assert len(partial) == 1
    assert "output truncated" in partial[0].message
    assert "scan was also incomplete" in partial[0].message


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


@pytest.mark.parametrize(
    "invalid_policy",
    [
        pytest.param(lambda: SourceFamilyPolicy(min_family_files=0), id="min-family"),
        pytest.param(lambda: SourceFamilyPolicy(max_files=0), id="max-files"),
        pytest.param(
            lambda: SourceFamilyPolicy(max_reported_members=0), id="max-members"
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(extensions=(".py", ".py")), id="extensions"
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(exclude=("../private/**",)), id="exclude"
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(file_length_limits=((".py", 0),)),
            id="file-length",
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(
                language_overrides=((".py", "Python"), (".py", "Py"))
            ),
            id="duplicate-language-override",
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(language_overrides=(("invalid", "Py"),)),
            id="invalid-language-override",
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(
                path_language_overrides=(("../outside/**", "C"),)
            ),
            id="invalid-path-language-override",
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(max_scope_patterns=1), id="scope-bound"
        ),
    ],
)
def test_rejects_invalid_source_family_policy(
    invalid_policy: Callable[[], SourceFamilyPolicy],
) -> None:
    with pytest.raises(ValueError):
        invalid_policy()
