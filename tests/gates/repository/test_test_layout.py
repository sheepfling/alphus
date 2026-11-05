"""Tests for configured Python source and test directory relationships."""

from __future__ import annotations

from pathlib import Path

import pytest

from alphus.gates.repository.test_layout import (
    TestLayoutRuleId as _TestLayoutRuleId,
)
from alphus.gates.repository.test_layout import (
    check_test_layout,
)
from alphus.policy.test_layout import (
    TestLayoutPair as _TestLayoutPair,
)
from alphus.policy.test_layout import (
    TestLayoutPolicy as _TestLayoutPolicy,
)


def _write(root: Path, relative: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n", encoding="utf-8")
    return Path(relative)


def _policy(
    *, integration_roots: tuple[str, ...] = ("integration",)
) -> _TestLayoutPolicy:
    return _TestLayoutPolicy(
        pairs=(
            _TestLayoutPair(
                source_root="src/example",
                test_root="tests",
                integration_roots=integration_roots,
            ),
        )
    )


def test_matching_source_modules_and_package_directories_pass(tmp_path: Path) -> None:
    files = [
        _write(tmp_path, "src/example/app.py"),
        _write(tmp_path, "src/example/dis/inbound.py"),
        _write(tmp_path, "tests/test_app.py"),
        _write(tmp_path, "tests/dis/test_inbound.py"),
        _write(tmp_path, "tests/conftest.py"),
    ]

    assert check_test_layout(tmp_path, files, _policy()) == []


def test_flat_test_for_nested_source_module_reports_mirrored_path(
    tmp_path: Path,
) -> None:
    files = [
        _write(tmp_path, "src/example/dis/inbound_receiver.py"),
        _write(tmp_path, "tests/test_inbound_receiver.py"),
    ]

    findings = check_test_layout(tmp_path, files, _policy())

    assert len(findings) == 1
    assert findings[0].rule_id == _TestLayoutRuleId.MODULE_MISPLACED
    assert findings[0].path == "tests/test_inbound_receiver.py"
    assert "tests/dis/test_inbound_receiver.py" in findings[0].message


def test_flattened_test_name_for_nested_source_is_detected(tmp_path: Path) -> None:
    files = [
        _write(tmp_path, "src/example/dis/inbound_receiver.py"),
        _write(tmp_path, "tests/test_dis_inbound_receiver.py"),
    ]

    findings = check_test_layout(tmp_path, files, _policy())

    assert findings[0].rule_id == _TestLayoutRuleId.MODULE_MISPLACED
    assert "tests/dis/test_inbound_receiver.py" in findings[0].message


def test_root_level_unmatched_test_must_be_declared_as_integration(
    tmp_path: Path,
) -> None:
    files = [
        _write(tmp_path, "src/example/app.py"),
        _write(tmp_path, "tests/test_database_workflow.py"),
    ]

    findings = check_test_layout(tmp_path, files, _policy())

    assert findings[0].rule_id == _TestLayoutRuleId.DIRECTORY_UNMIRRORED
    assert "integration root" in findings[0].message


def test_configured_integration_root_allows_cross_module_tests(tmp_path: Path) -> None:
    files = [
        _write(tmp_path, "src/example/app.py"),
        _write(tmp_path, "tests/acceptance/test_server_workflow.py"),
    ]

    assert (
        check_test_layout(
            tmp_path,
            files,
            _policy(integration_roots=("acceptance",)),
        )
        == []
    )


def test_unmatched_nested_test_directory_is_reported(tmp_path: Path) -> None:
    files = [
        _write(tmp_path, "src/example/work/jobs.py"),
        _write(tmp_path, "tests/other/test_queue.py"),
    ]

    findings = check_test_layout(tmp_path, files, _policy())

    assert findings[0].rule_id == _TestLayoutRuleId.DIRECTORY_UNMIRRORED
    assert "other" in findings[0].message


def test_unavailable_configured_roots_are_reported(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    files = [_write(tmp_path, "tests/test_app.py")]

    findings = check_test_layout(tmp_path, files, _policy())

    assert [finding.rule_id for finding in findings] == [
        _TestLayoutRuleId.ROOT_UNAVAILABLE
    ]
    assert findings[0].path == "src/example"


@pytest.mark.parametrize(
    ("source_root", "test_root", "integration_roots", "message"),
    [
        (".", "tests", ("integration",), "source_root"),
        ("src/example", "src/example", ("integration",), "different"),
        (
            "src/example",
            "tests",
            ("integration", "integration"),
            "unique",
        ),
    ],
)
def test_invalid_layout_roots_are_rejected(
    source_root: str,
    test_root: str,
    integration_roots: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _TestLayoutPair(
            source_root=source_root,
            test_root=test_root,
            integration_roots=integration_roots,
        )


def test_policy_rejects_reused_test_roots() -> None:
    with pytest.raises(ValueError, match="one source root"):
        _TestLayoutPolicy(
            pairs=(
                _TestLayoutPair(source_root="src/one", test_root="tests"),
                _TestLayoutPair(source_root="src/two", test_root="tests"),
            )
        )
