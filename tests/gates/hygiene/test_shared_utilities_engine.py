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
from alphus.gates.languages.python.runtime_types import type_check_findings

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
    canonical_byte_hash_path="src/common/bytes.py",
    canonical_byte_hash_function="bytes_sha256",
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
canonical_byte_hash_path = "src/common/bytes.py"
canonical_byte_hash_function = "bytes_sha256"
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


def test_duplicate_helpers_exclude_only_conventional_cli_wrappers(
    tmp_path: Path,
) -> None:
    first = (
        "def main():\n    raise SystemExit(cli())\n"
        "def normalize(value):\n"
        "    cleaned = value.strip()\n"
        "    if not cleaned:\n        raise ValueError('empty')\n"
        "    return cleaned\n"
    )
    second = first.replace("normalize", "clean_name")
    _write(tmp_path, "src/first.py", first)
    _write(tmp_path, "src/second.py", second)
    policy = POLICY.model_copy(
        update={"minimum_body_statements": 1, "minimum_ast_nodes": 1}
    )
    groups = duplicate_helpers(
        tmp_path, [Path("src/first.py"), Path("src/second.py")], policy
    )
    assert list(groups.values()) == [
        ["src/first.py:normalize", "src/second.py:clean_name"]
    ]


def test_intentionally_mirrored_test_fixtures_remain_excluded(tmp_path: Path) -> None:
    mirrored = (
        "def assert_fixture_contract(value):\n"
        "    parsed = parse(value)\n"
        "    if parsed is None:\n"
        "        raise AssertionError('fixture rejected')\n"
        "    return parsed\n"
    )
    first = Path("tests/fixtures/positive_contract.py")
    second = Path("tests/fixtures/negative_control.py")
    _write(tmp_path, first.as_posix(), mirrored)
    _write(tmp_path, second.as_posix(), mirrored)

    assert duplicate_helpers(tmp_path, [first, second], POLICY) == {}


def test_cli_wrapper_ast_shape_does_not_look_like_runtime_input_narrowing() -> None:
    source = """import ast
def is_cli_wrapper(body):
    match body[0]:
        case ast.Raise(
            exc=ast.Call(
                func=ast.Name(id="SystemExit"),
                args=[ast.Call(keywords=[])],
                keywords=[],
            )
        ):
            return True
        case _:
            return False
"""
    assert type_check_findings(source) == []


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


def test_byte_hash_scan_reports_repeated_named_inputs_and_skips_owner(
    tmp_path: Path,
) -> None:
    sources = {
        "src/common/bytes.py": (
            "import hashlib\n"
            "def bytes_sha256(payload):\n"
            "    return hashlib.sha256(payload).digest()\n"
        ),
        "src/first.py": (
            "import hashlib\n"
            "def first_digest(payload):\n"
            "    return hashlib.sha256(payload).hexdigest()\n"
        ),
        "src/second.py": (
            "import hashlib\n"
            "def second_digest(content):\n"
            "    return hashlib.sha256(content).hexdigest()\n"
        ),
    }
    for name, source in sources.items():
        _write(tmp_path, name, source)

    paths = [Path(name) for name in sources]
    report = check_shared_utilities(tmp_path, paths, POLICY)

    assert report.byte_hash_implementations == (
        "src/first.py:2:first_digest",
        "src/second.py:2:second_digest",
    )
    assert report.failed


def test_byte_hash_scan_is_disabled_without_a_configured_owner(
    tmp_path: Path,
) -> None:
    for name in ("first", "second"):
        _write(
            tmp_path,
            f"src/{name}.py",
            "import hashlib\n"
            f"def {name}(payload):\n"
            "    return hashlib.sha256(payload).hexdigest()\n",
        )
    policy = POLICY.model_copy(
        update={
            "canonical_byte_hash_path": None,
            "canonical_byte_hash_function": None,
        }
    )

    report = check_shared_utilities(
        tmp_path,
        [Path("src/first.py"), Path("src/second.py")],
        policy,
    )

    assert report.byte_hash_implementations == ()
    assert not report.failed


def test_byte_hash_scan_keeps_single_use_and_embedded_probe_clean(
    tmp_path: Path,
) -> None:
    source = (
        "import hashlib\n"
        "def recipe_identity(payload):\n"
        "    return hashlib.sha256(payload).hexdigest()\n"
        "PROBE = 'hashlib.sha256(payload).hexdigest()'\n"
    )
    _write(tmp_path, "src/recipe.py", source)

    report = check_shared_utilities(tmp_path, [Path("src/recipe.py")], POLICY)

    assert report.byte_hash_implementations == ("src/recipe.py:2:recipe_identity",)
    assert not report.failed


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
    assert report.byte_hash_implementations == ()
    assert report.direct_git_calls == ()
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
    _write(
        tmp_path,
        "src/byte_first.py",
        "import hashlib\ndef direct_bytes(payload):\n"
        "    return hashlib.sha256(payload).digest()\n",
    )
    _write(
        tmp_path,
        "src/byte_second.py",
        "import hashlib\ndef other_direct_bytes(content):\n"
        "    return hashlib.sha256(content).digest()\n",
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
    assert "Direct in-memory SHA-256 implementations: 2" in output
    assert (
        "alphus/python/none/maintainability/duplicate-byte-hash-implementation:"
        in output
    )

    assert main([*arguments, "--report", "--json"]) == 0
    assert capsys.readouterr().out == (
        '{"byte_hash_implementations": ["src/byte_first.py:2:direct_bytes", '
        '"src/byte_second.py:2:other_direct_bytes"], "direct_git_calls": [], '
        '"duplicate_groups": [], "failed": true, '
        '"file_hash_implementations": ["src/first.py:2:direct", '
        '"src/second.py:2:streamed"]}\n'
    )


def test_shared_utilities_reports_direct_git_launches(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/raw.py",
        "import subprocess\ndef revision(root):\n"
        '    return subprocess.run(["git", "status"], cwd=root)\n',
    )
    report = check_shared_utilities(tmp_path, [Path("src/raw.py")], POLICY)
    assert report.direct_git_calls == ("src/raw.py:3",)
    assert report.failed
