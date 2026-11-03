"""Prepare a disposable, documented fixture copy for the mdutils stub trial."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from alphus.support.git import git_value
from alphus.support.source_text import read_utf8_text

CONSUMER_REVISION = "777b4b600e128721493999ed48867fa664f1a573"
POSITIVE_REPLACEMENTS = (
    (
        "assert_type(document.textUtils, type[TextUtilsClass])",
        "document_text_utils: type[TextUtilsClass] = document.textUtils",
    ),
    (
        "assert_type(mdutils.TextUtils, type[TextUtilsClass])",
        "mdutils_text_utils: type[TextUtilsClass] = mdutils.TextUtils",
    ),
    (
        "assert_type(ToolsTextUtils, type[TextUtilsClass])",
        "tools_text_utils: type[TextUtilsClass] = ToolsTextUtils",
    ),
)


def _package_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "mdutils-stubs").rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def prepare(root: Path) -> None:
    """Create calibrated test files without changing consumer sources or stubs."""
    root = root.resolve()
    pyproject = read_utf8_text(root / "pyproject.toml")
    license_text = read_utf8_text(root / "LICENSE")
    revision = git_value(root, "rev-parse", "--verify", "HEAD")
    if revision != CONSUMER_REVISION:
        raise ValueError(f"unexpected consumer revision: {revision}")
    if 'name = "mdutils-stubs"' not in pyproject or "mdutils==1.8.1" not in pyproject:
        raise ValueError("consumer metadata no longer matches the recorded trial")
    if 'license = "MIT"' not in pyproject or "MIT License" not in license_text:
        raise ValueError("consumer license no longer matches the reviewed MIT source")

    before = _package_digest(root)
    fixture_dir = root / "tests" / "fixtures"
    positive = read_utf8_text(fixture_dir / "positive.py")
    calibrated_positive = positive
    for original, replacement in POSITIVE_REPLACEMENTS:
        if calibrated_positive.count(original) != 1:
            raise ValueError(f"expected exactly one class-object probe: {original}")
        calibrated_positive = calibrated_positive.replace(original, replacement)
    (fixture_dir / "positive_calibrated.py").write_text(
        calibrated_positive, encoding="utf-8"
    )

    negative = read_utf8_text(fixture_dir / "negative.py")
    if "# expect-error" in negative:
        raise ValueError("negative fixture unexpectedly already has Alphus markers")
    negative_lines = negative.splitlines()
    expected_calls = (
        "document = MdUtils(file_name=42)",
        'document.new_header(level="first", title=7)',
        "document.new_table(columns=1, rows=1, text=[7], text_align=4)",
        "TextUtils.text_format(text=42)",
    )
    if tuple(line.strip() for line in negative_lines[2:]) != expected_calls:
        raise ValueError("negative fixture differs from the reviewed four-call corpus")
    for index in range(2, len(negative_lines)):
        negative_lines[index] += "  # expect-error"
    (fixture_dir / "negative_calibrated.py").write_text(
        "\n".join(negative_lines) + "\n", encoding="utf-8"
    )
    (root / "tests" / "__init__.py").write_text(
        '"""Consumer runtime probes for the isolated CI trial."""\n', encoding="utf-8"
    )

    config = {
        "verification": {
            "stubtest_module": "mdutils",
            "stubtest_allowlist": "stubtest-allowlist.txt",
            "positive_fixture": "tests/fixtures/positive_calibrated.py",
            "negative_fixture": "tests/fixtures/negative_calibrated.py",
            "runtime_smoke_module": "tests.runtime_api",
            "typing_checkers": ["mypy", "pyright", "ty"],
            "mypy_diagnostics": ["[arg-type]"],
            "pyright_diagnostics": ["reportArgumentType"],
            "ty_diagnostics": ["invalid-argument-type"],
        }
    }
    (root / "stub-quality.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    if _package_digest(root) != before:
        raise AssertionError("fixture preparation changed the stub package tree")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consumer-root", required=True, type=Path)
    options = parser.parse_args()
    prepare(options.consumer_root)


if __name__ == "__main__":
    main()
