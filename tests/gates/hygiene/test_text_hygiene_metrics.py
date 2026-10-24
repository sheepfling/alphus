"""Exact unit and boundary behavior for shared line and file checks."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import FileSizePolicy, LineLengthPolicy, QualityGateConfig
from alphus.gates.hygiene.rules import check_file_size, check_line_length


def line_config(
    *,
    limits: dict[str, int] | None = None,
    path_limits: dict[str, int] | None = None,
    exclude: tuple[str, ...] = (),
) -> QualityGateConfig:
    """Build a minimal policy that selects the line-length rule only."""
    return QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "line_length": {
                    "codepoint_limits": limits or {},
                    "path_codepoint_limits": path_limits or {},
                    "exclude": exclude,
                }
            },
        }
    )


def size_config(
    *,
    code_lines: int = 100,
    hard_lines: int = 200,
    raw_bytes: int | None = None,
    extension_bytes: dict[str, int] | None = None,
    path_bytes: dict[str, int] | None = None,
    exclude: tuple[str, ...] = (),
) -> QualityGateConfig:
    """Build a minimal policy that selects the file-size rule only."""
    return QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "file_size": {
                    "code_extensions": [".py"],
                    "code_physical_line_limit": code_lines,
                    "hard_physical_line_limit": hard_lines,
                    "raw_byte_limit": raw_bytes,
                    "raw_byte_limits": extension_bytes or {},
                    "path_raw_byte_limits": path_bytes or {},
                    "initializer_name": "__init__.py",
                    "initializer_limit": 100,
                    "exclude": exclude,
                }
            },
        }
    )


def write_bytes(root: Path, name: str, content: bytes) -> Path:
    """Write one fixture and return its repository-relative path."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return Path(name)


@pytest.mark.parametrize(
    ("content", "expected_lines"),
    [
        (b"", 0),
        (b"one\n", 1),
        (b"one\ntwo\n", 2),
        (b"one\r\ntwo\r\n", 2),
        (b"one\ntwo", 2),
        (b"\n# comment\nx\n", 3),
        (b"one\rtwo\r", 2),
        (b"a" * 65535 + b"\r\nb", 2),
    ],
)
def test_file_size_counts_physical_lines_without_decoding(
    tmp_path: Path, content: bytes, expected_lines: int
) -> None:
    """LF, CRLF, CR, blank lines, comments, and EOF follow one physical-line rule."""
    relative = write_bytes(tmp_path, "src/example.py", content)
    findings = check_file_size(
        tmp_path,
        [relative],
        size_config(code_lines=max(expected_lines, 1), hard_lines=20),
    )
    assert findings == []

    if expected_lines > 1:
        findings = check_file_size(
            tmp_path,
            [relative],
            size_config(code_lines=expected_lines - 1, hard_lines=20),
        )
        assert len(findings) == 1
        assert f"{expected_lines} physical lines" in findings[0].message


def test_file_size_old_names_keep_physical_line_semantics() -> None:
    """Existing TOML keys remain accepted as aliases for explicit physical-line limits."""
    config = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "file_size": {
                    "code_extensions": [".py"],
                    "code_limit": 3,
                    "hard_limit": 8,
                    "initializer_name": "__init__.py",
                    "initializer_limit": 2,
                }
            },
        }
    )
    assert config.checks.file_size is not None
    assert config.checks.file_size.effective_code_physical_line_limit == 3
    assert config.checks.file_size.effective_hard_physical_line_limit == 8
    assert config.checks.file_size.code_limit == 3
    assert config.checks.file_size.model_dump()["code_limit"] == 3


def test_file_size_accepts_matching_old_and_explicit_names() -> None:
    """Equivalent migration keys are accepted and retain legacy Python attributes."""
    config = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "file_size": {
                    "code_extensions": [".py"],
                    "code_limit": 3,
                    "code_physical_line_limit": 3,
                    "hard_limit": 8,
                    "hard_physical_line_limit": 8,
                    "initializer_name": "__init__.py",
                    "initializer_limit": 2,
                }
            },
        }
    )
    assert config.checks.file_size is not None
    assert config.checks.file_size.code_limit == 3
    assert config.checks.file_size.hard_limit == 8


def test_hard_physical_line_limit_applies_to_non_code_files(tmp_path: Path) -> None:
    """The all-file physical-line cap stays separate from the code-file limit."""
    relative = write_bytes(tmp_path, "docs/notes.md", b"one\r\ntwo")
    config = size_config(code_lines=1, hard_lines=2)
    assert check_file_size(tmp_path, [relative], config) == []

    relative = write_bytes(tmp_path, "docs/notes.md", b"one\r\ntwo\r\nthree")
    findings = check_file_size(tmp_path, [relative], config)
    assert len(findings) == 1
    assert findings[0].rule_id == (
        "alphus/any/none/maintainability/file-exceeds-hard-limit"
    )
    assert "3 physical lines" in findings[0].message


def test_public_policy_json_schema_documents_metric_units() -> None:
    """The Pydantic schema makes legacy names and new measurement units explicit."""
    file_size = FileSizePolicy.model_json_schema()["properties"]
    line_length = LineLengthPolicy.model_json_schema()["properties"]
    assert "physical lines" in file_size["code_physical_line_limit"]["description"]
    assert "raw bytes" in file_size["raw_byte_limit"]["description"]
    assert "Unicode code points" in line_length["codepoint_limits"]["description"]


def test_line_length_rejects_empty_or_conflicting_extension_tables() -> None:
    """A selected line rule must have a limit, and old/new aliases cannot disagree."""
    with pytest.raises(ValidationError, match="configure an extension or path"):
        LineLengthPolicy.model_validate({})
    with pytest.raises(ValidationError, match="cannot conflict"):
        LineLengthPolicy.model_validate(
            {"limits": {".py": 80}, "codepoint_limits": {".py": 100}}
        )


def test_file_size_rejects_conflicting_legacy_and_explicit_line_limits() -> None:
    """A policy cannot silently pick between two different values for one unit."""
    with pytest.raises(ValidationError, match="cannot specify different limits"):
        QualityGateConfig.model_validate(
            {
                "schema_version": 1,
                "checks": {
                    "file_size": {
                        "code_extensions": [".py"],
                        "code_limit": 3,
                        "code_physical_line_limit": 4,
                        "hard_limit": 8,
                        "initializer_name": "__init__.py",
                        "initializer_limit": 2,
                    }
                },
            }
        )


def test_line_length_counts_codepoints_and_keeps_tabs_spaces_and_combining_marks(
    tmp_path: Path,
) -> None:
    """Line width is Unicode code-point count, not visual columns or graphemes."""
    files = [
        write_bytes(tmp_path, "src/equal.py", b"ab\n"),
        write_bytes(tmp_path, "src/tab.py", b"\tAB\n"),
        write_bytes(tmp_path, "src/space.py", b"a  \n"),
        write_bytes(tmp_path, "src/combining.py", "e\u0301x\n".encode()),
        write_bytes(tmp_path, "src/bom.py", b"\xef\xbb\xbf" + b"ab\n"),
    ]

    findings = check_line_length(tmp_path, files, line_config(limits={".py": 2}))

    assert {finding.path for finding in findings} == {
        "src/bom.py",
        "src/combining.py",
        "src/space.py",
        "src/tab.py",
    }
    assert all(finding.line == 1 for finding in findings)
    assert all("Unicode code points" in finding.message for finding in findings)
    bom_finding = next(finding for finding in findings if finding.path == "src/bom.py")
    assert "3 Unicode code points" in bom_finding.message


@pytest.mark.parametrize(
    ("content", "expected_line"),
    [(b"", None), (b"abc", 1), (b"a\r\nabc\r\n", 2)],
)
def test_line_length_handles_empty_unterminated_and_crlf_files(
    tmp_path: Path, content: bytes, expected_line: int | None
) -> None:
    """Only LF, CRLF, and CR delimit physical lines; a final terminator adds no line."""
    relative = write_bytes(tmp_path, "src/line.py", content)
    findings = check_line_length(tmp_path, [relative], line_config(limits={".py": 2}))
    assert [finding.line for finding in findings] == (
        [] if expected_line is None else [expected_line]
    )


def test_line_length_reports_invalid_utf8_without_reporting_a_clean_file(
    tmp_path: Path,
) -> None:
    """Invalid configured text yields a stable encoding diagnostic with byte offset."""
    relative = write_bytes(tmp_path, "src/invalid.py", b"value = \xff\n")

    findings = check_line_length(tmp_path, [relative], line_config(limits={".py": 100}))

    assert len(findings) == 1
    assert findings[0].rule_id == "alphus/any/none/style/invalid-text-encoding"
    assert "invalid byte sequence" in findings[0].message


def test_line_length_path_overrides_extension_and_uses_stable_specificity(
    tmp_path: Path,
) -> None:
    """An exact path beats a glob, which beats an extension default, regardless of order."""
    exact = write_bytes(tmp_path, "src/deep/special.py", b"abcd\n")
    glob = write_bytes(tmp_path, "src/deep/other.py", b"abcd\n")
    extension = write_bytes(tmp_path, "lib/other.py", b"abc\n")
    overrides = {
        "src/**/*.py": 3,
        "src/deep/special.py": 4,
    }
    reversed_overrides = dict(reversed(list(overrides.items())))

    for selected_overrides in (overrides, reversed_overrides):
        findings = check_line_length(
            tmp_path,
            [exact, glob, extension],
            line_config(limits={".py": 2}, path_limits=selected_overrides),
        )
        assert [(finding.path, finding.message) for finding in findings] == [
            (
                "src/deep/other.py",
                "physical line has 4 Unicode code points (limit 3 Unicode code points)",
            ),
            (
                "lib/other.py",
                "physical line has 3 Unicode code points (limit 2 Unicode code points)",
            ),
        ]


def test_path_override_ties_use_lexical_pattern_order(tmp_path: Path) -> None:
    """Equally specific overlapping globs use the documented lexical tie-break."""
    relative = write_bytes(tmp_path, "src/deep/special.py", b"abcd\n")
    overrides = {
        "src/dee*/special.py": 4,
        "src/de*p/special.py": 3,
    }

    for path_limits in (overrides, dict(reversed(list(overrides.items())))):
        findings = check_line_length(
            tmp_path,
            [relative],
            line_config(path_limits=path_limits),
        )
        assert len(findings) == 1
        assert "limit 3 Unicode code points" in findings[0].message


def test_file_size_raw_bytes_have_global_extension_and_path_precedence(
    tmp_path: Path,
) -> None:
    """Byte counts use raw bytes, and the most specific configured limit wins."""
    empty = write_bytes(tmp_path, "lib/empty.py", b"")
    equal = write_bytes(tmp_path, "lib/equal.py", b"12345")
    too_large = write_bytes(tmp_path, "lib/large.py", b"123456")
    path_override = write_bytes(tmp_path, "src/special.py", b"1234")
    glob_override = write_bytes(tmp_path, "src/nested/special.py", b"1234")
    overrides = {"src/**/*.py": 4, "src/special.py": 3}
    for path_limits in (overrides, dict(reversed(list(overrides.items())))):
        findings = check_file_size(
            tmp_path,
            [empty, equal, too_large, path_override, glob_override],
            size_config(
                raw_bytes=4,
                extension_bytes={".py": 5},
                path_bytes=path_limits,
            ),
        )

        assert [
            (finding.path, finding.message, finding.severity) for finding in findings
        ] == [
            (
                "lib/large.py",
                "file has 6 raw bytes (limit 5 raw bytes)",
                "warning",
            ),
            (
                "src/special.py",
                "file has 4 raw bytes (limit 3 raw bytes)",
                "warning",
            ),
        ]


def test_raw_byte_limit_includes_bom_and_crlf_bytes(tmp_path: Path) -> None:
    """Raw-byte measurements include BOM and line-terminator bytes exactly."""
    relative = write_bytes(tmp_path, "assets/payload.bin", b"\xef\xbb\xbfA\r\n")
    config = size_config(raw_bytes=5)

    findings = check_file_size(tmp_path, [relative], config)

    assert len(findings) == 1
    assert findings[0].message == "file has 6 raw bytes (limit 5 raw bytes)"


def test_binary_and_generated_paths_are_skipped_by_explicit_exclusions(
    tmp_path: Path,
) -> None:
    """Consumers exclude binary and generated paths instead of relying on guessing."""
    binary = write_bytes(tmp_path, "assets/data.bin", b"\x00\xffbinary payload")
    generated = write_bytes(tmp_path, "build/generated/output.py", b"x" * 100)
    findings = check_file_size(
        tmp_path,
        [binary, generated],
        size_config(
            raw_bytes=1,
            exclude=("**/*.bin", "build/generated/**"),
        ),
    )
    assert findings == []
