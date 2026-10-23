"""Compatibility forwarders need tracked and expiring removal plans."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from alphus.gates.python.compatibility import (
    check_forwarders,
    discover_forwarders,
    load_removal_plans,
)
from alphus.gates.python.compatibility_cli import main


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / "src"
    package = root / "sample"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from .current import Thing\n", encoding="utf-8"
    )
    (package / "current.py").write_text("class Thing:\n    pass\n", encoding="utf-8")
    return root


def _write_plan(tmp_path: Path, *, remove_by: str = "2027-01-01") -> Path:
    path = tmp_path / "compatibility-imports.toml"
    path.write_text(
        "schema_version = 1\n"
        "[[forwarders]]\n"
        'module = "sample.old"\n'
        'replacement = "sample.current:Thing"\n'
        'owner = "package maintainers"\n'
        f"remove_by = {remove_by}\n",
        encoding="utf-8",
    )
    return path


def test_detects_named_import_forwarder_but_not_normal_package_exports(
    tmp_path: Path,
) -> None:
    root = _source_root(tmp_path)
    (root / "sample" / "old.py").write_text(
        '"""Old import path."""\n'
        "from sample.current import Thing\n"
        '__all__ = ["Thing"]\n',
        encoding="utf-8",
    )
    (root / "sample" / "__main__.py").write_text(
        "from sample.current import Thing\n"
        'if __name__ == "__main__":\n'
        "    print(Thing)\n",
        encoding="utf-8",
    )

    forwarders, issues = discover_forwarders(root)

    assert issues == ()
    assert [(item.module, item.reason) for item in forwarders] == [
        ("sample.old", "import-only forwarder")
    ]


def test_detects_wildcard_and_explicit_compatibility_marker(
    tmp_path: Path,
) -> None:
    root = _source_root(tmp_path)
    (root / "sample" / "wildcard.py").write_text(
        "from sample.current import *\ndef helper() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (root / "sample" / "marked.py").write_text(
        '"""Compatibility imports for an old API."""\n'
        "from sample.current import Thing\n"
        "def helper() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (root / "sample" / "marked_comment.py").write_text(
        "from sample.current import Thing\n"
        "# " + "TO" + "DO get rid of this compat import.\n"
        "def helper() -> None:\n    pass\n",
        encoding="utf-8",
    )

    forwarders, issues = discover_forwarders(root)

    assert issues == ()
    assert {item.module: item.reason for item in forwarders} == {
        "sample.marked": "marked compatibility import",
        "sample.marked_comment": "marked compatibility import",
        "sample.wildcard": "wildcard import",
    }


def test_unplanned_forwarder_fails(tmp_path: Path) -> None:
    root = _source_root(tmp_path)
    (root / "sample" / "old.py").write_text(
        "from sample.current import Thing\n", encoding="utf-8"
    )

    issues, planned = check_forwarders(root, today=date(2026, 1, 1))

    assert planned == ()
    assert issues == (
        "sample/old.py: import-only forwarder sample.old has no removal plan",
    )


def test_valid_plan_reports_owner_replacement_and_removal_date(
    tmp_path: Path,
) -> None:
    root = _source_root(tmp_path)
    (root / "sample" / "old.py").write_text(
        "from sample.current import Thing\n", encoding="utf-8"
    )

    issues, planned = check_forwarders(
        root, _write_plan(tmp_path), today=date(2026, 1, 1)
    )

    assert issues == ()
    assert planned == (
        (
            "sample.old -> sample.current:Thing; owner=package maintainers; "
            "remove_by=2027-01-01"
        ),
    )


def test_expired_and_stale_plans_fail(tmp_path: Path) -> None:
    root = _source_root(tmp_path)
    (root / "sample" / "old.py").write_text(
        "from sample.current import Thing\n", encoding="utf-8"
    )
    plan = _write_plan(tmp_path)

    expired, planned = check_forwarders(root, plan, today=date(2027, 1, 1))
    assert planned == ()
    assert expired == (
        "sample/old.py: removal plan for sample.old expired on 2027-01-01",
    )

    (root / "sample" / "old.py").unlink()
    stale, planned = check_forwarders(root, plan, today=date(2026, 1, 1))
    assert planned == ()
    assert stale == (
        "sample.old: stale removal plan; forwarding module no longer exists",
    )


def test_plan_requires_strict_fields_and_date(tmp_path: Path) -> None:
    plan = _write_plan(tmp_path, remove_by='"2027-01-01"')

    entries, issues = load_removal_plans(plan)

    assert entries == {}
    assert len(issues) == 1
    assert "remove_by must be a TOML date" in issues[0]


def test_cli_fails_for_unplanned_forwarder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _source_root(tmp_path)
    (root / "sample" / "old.py").write_text(
        "from sample.current import Thing\n", encoding="utf-8"
    )

    assert main(["--source-root", str(root)]) == 1
    assert "has no removal plan" in capsys.readouterr().out
