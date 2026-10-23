"""Portable duplicate-helper and file-hash analysis tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alphus.cli import main
from alphus.config import SharedUtilitiesPolicy
from alphus.gates.hygiene.shared_utilities import (
    check_shared_utilities,
    duplicate_helpers,
    file_sha256_helpers,
)

POLICY = SharedUtilitiesPolicy(
    extensions=[".py"],
    exclude=[
        "**/vendor/**",
        "vendor/**",
        "**/tests/**",
        "tests/**",
        "**/test_*",
        "test_*",
    ],
    canonical_file_hash_path="src/common/files.py",
    canonical_file_hash_function="sha256_file",
    minimum_body_statements=3,
    minimum_ast_nodes=15,
)

CLI_CONFIG = """schema_version = 1

[files]
include = ["**/*.py", "*.py"]
exclude = []

[checks.file_size]
code_extensions = [".py"]
code_limit = 3000
hard_limit = 5000
initializer_name = "__init__.py"
initializer_limit = 100
exclude = []

[checks.line_length]
exclude = []

[checks.line_length.limits]
".py" = 120

[checks.json_structure]
extensions = [".py"]
exclude = []

[checks.output_escaping]
extensions = [".py"]
exclude = []

[checks.path_discovery]
extensions = [".py"]
exclude = []
inspection_exclude = []

[checks.shared_utilities]
extensions = [".py"]
exclude = []
canonical_file_hash_path = "src/common/files.py"
canonical_file_hash_function = "sha256_file"
minimum_body_statements = 3
minimum_ast_nodes = 15

[checks.python_style]
extensions = [".py"]
exclude = []
opaque_boundary_paths = ["src/adapters/**"]
opaque_boundary_marker_prefix = "# opaque-boundary: "
opaque_boundary_min_reason_chars = 12
forbidden_main_imports = ["main", "service.app"]

[checks.runtime_types]
extensions = [".py"]
exclude = ["**/tests/**", "tests/**", "**/test_*", "test_*"]
"""


def _write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _cli_repository(root: Path) -> None:
    subprocess.run(
        ["git", "init", "--quiet", str(root)], check=True, capture_output=True
    )
    _write(root, "quality.toml", CLI_CONFIG)


def test_duplicate_helpers_ignore_names_and_docstrings_but_exclude_tests(
    tmp_path: Path,
) -> None:
    first = (
        'def first_digest(path):\n    """First helper."""\n'
        "    result = path.read_bytes()\n    if not result:\n"
        "        raise ValueError()\n    return result.hex()\n"
    )
    second = first.replace("first_digest", "renamed_digest").replace(
        "First helper.", "A different docstring."
    )
    _write(tmp_path, "src/first.py", first)
    _write(tmp_path, "src/second.py", second)
    _write(tmp_path, "src/test_ignored.py", second)
    _write(tmp_path, "src/vendor/ignored.py", second)
    paths = [
        Path("src/first.py"),
        Path("src/second.py"),
        Path("src/test_ignored.py"),
        Path("src/vendor/ignored.py"),
    ]

    groups = duplicate_helpers(tmp_path, paths, POLICY)

    assert list(groups.values()) == [
        ["src/first.py:first_digest", "src/second.py:renamed_digest"]
    ]


def test_duplicate_helpers_find_class_methods_with_qualified_names(
    tmp_path: Path,
) -> None:
    """Method duplicates retain their owning class in the report location."""
    first = (
        "class FirstStore:\n"
        "    def digest(self, path):\n"
        "        data = path.read_bytes()\n"
        "        if not data:\n"
        "            raise ValueError('empty')\n"
        "        return data.hex()\n"
    )
    second = first.replace("FirstStore", "SecondStore").replace("digest", "encode")
    _write(tmp_path, "src/first.py", first)
    _write(tmp_path, "src/second.py", second)

    groups = duplicate_helpers(
        tmp_path,
        [Path("src/first.py"), Path("src/second.py")],
        POLICY,
    )

    assert list(groups.values()) == [
        ["src/first.py:FirstStore.digest", "src/second.py:SecondStore.encode"]
    ]


def test_file_hash_scan_skips_configured_canonical_and_non_file_hashes(
    tmp_path: Path,
) -> None:
    modules = {
        "src/common/files.py": (
            "import hashlib\n"
            "def sha256_file(path):\n"
            "    digest = hashlib.sha256()\n"
            "    with path.open('rb') as stream:\n"
            "        for chunk in iter(lambda: stream.read(4096), b''):\n"
            "            digest.update(chunk)\n"
            "    return digest.hexdigest()\n"
        ),
        "src/direct.py": (
            "import hashlib\n"
            "def checksum(path):\n"
            "    return hashlib.sha256(path.read_bytes()).hexdigest()\n"
        ),
        "src/stream.py": (
            "import hashlib\n"
            "def digest_file(path):\n"
            "    digest = hashlib.sha256()\n"
            "    with path.open('rb') as stream:\n"
            "        digest.update(stream.read())\n"
            "    return digest.hexdigest()\n"
        ),
        "src/class_method.py": (
            "import hashlib\n"
            "class FileHasher:\n"
            "    def checksum(self, path):\n"
            "        return hashlib.sha256(path.read_bytes()).hexdigest()\n"
        ),
        "src/bytes_only.py": (
            "import hashlib\n"
            "def digest(payload):\n"
            "    return hashlib.sha256(payload).hexdigest()\n"
        ),
        "tests/test_file_hash.py": (
            "import hashlib\n"
            "def ignored(path):\n"
            "    return hashlib.sha256(path.read_bytes()).hexdigest()\n"
        ),
    }
    for name, source in modules.items():
        _write(tmp_path, name, source)
    paths = [Path(name) for name in modules]

    assert file_sha256_helpers(tmp_path, paths, POLICY) == [
        "src/class_method.py:3:FileHasher.checksum",
        "src/direct.py:2:checksum",
        "src/stream.py:2:digest_file",
    ]


def test_report_exposes_success_metrics_and_failure_state(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/one.py",
        "import hashlib\ndef checksum(path):\n"
        "    return hashlib.sha256(path.read_bytes()).hexdigest()\n",
    )
    report = check_shared_utilities(tmp_path, [Path("src/one.py")], POLICY)

    assert report.duplicate_groups == ()
    assert report.file_hash_implementations == ("src/one.py:2:checksum",)
    assert not report.failed


def test_shared_utilities_cli_reports_groups_and_machine_readable_metrics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cli_repository(tmp_path)
    _write(
        tmp_path,
        "src/first.py",
        "import hashlib\ndef direct(path):\n"
        "    return hashlib.sha256(path.read_bytes()).hexdigest()\n",
    )
    _write(
        tmp_path,
        "src/second.py",
        "import hashlib\ndef streamed(path):\n"
        "    digest = hashlib.sha256()\n"
        "    with path.open('rb') as stream:\n"
        "        digest.update(stream.read())\n"
        "    return digest.hexdigest()\n",
    )
    arguments = [
        "--root",
        str(tmp_path),
        "--config",
        "quality.toml",
        "--rule",
        "shared-utilities",
    ]

    assert main(arguments) == 1
    output = capsys.readouterr().out
    assert (
        "alphus/python/none/maintainability/duplicate-file-hash-implementation:"
        in output
    )
    assert "File SHA-256 copies outside the shared helper: 2" in output

    assert main([*arguments, "--report", "--json"]) == 0
    assert capsys.readouterr().out == (
        '{"duplicate_groups": [], "failed": true, '
        '"file_hash_implementations": ["src/first.py:2:direct", '
        '"src/second.py:2:streamed"]}\n'
    )
