"""Portable requirement declaration and exact lock consistency checks."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import DependencyLockPolicy
from alphus.dependency_locks import check_dependency_locks


def _policy() -> DependencyLockPolicy:
    return DependencyLockPolicy.model_validate(
        {
            "pairs": [
                {"input_file": "config/requirements.txt", "lock_file": "locks/base.txt"}
            ],
            "exact_pin_files": ["locks/build.txt"],
        }
    )


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_exact_satisfying_lock_and_build_pins_pass(tmp_path: Path) -> None:
    _write(tmp_path, "config/requirements.txt", "service-kit>=1.0\n")
    _write(tmp_path, "locks/base.txt", "service_kit==1.4.2\n")
    _write(tmp_path, "locks/build.txt", "builder==3.2.0\n")

    assert check_dependency_locks(tmp_path, _policy()) == []


def test_nonexact_and_missing_pins_are_reported(tmp_path: Path) -> None:
    _write(tmp_path, "config/requirements.txt", "service-kit>=1.0\nother-lib>=2\n")
    _write(tmp_path, "locks/base.txt", "service-kit==0.5.0\nfloating-lib>=4\n")
    _write(tmp_path, "locks/build.txt", "builder>=3.0\n")

    findings = check_dependency_locks(tmp_path, _policy())

    assert [finding.message for finding in findings] == [
        "floating-lib needs one exact version pin",
        "service-kit pin does not satisfy config/requirements.txt",
        "missing declared requirement other-lib from config/requirements.txt",
        "builder needs one exact version pin",
    ]


def test_nested_requirement_includes_and_url_sources_are_supported(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "config/requirements.txt",
        "-r nested/base.txt\nsource-kit @ https://example.invalid/source-kit.whl\n",
    )
    _write(tmp_path, "config/nested/base.txt", "service-kit>=1.0\n")
    _write(
        tmp_path,
        "locks/base.txt",
        "--requirement nested/base.txt\n"
        "service-kit==1.4.2\n"
        "source-kit @ https://example.invalid/source-kit.whl\n",
    )
    _write(tmp_path, "locks/nested/base.txt", "service-kit==1.4.2\n")
    _write(
        tmp_path, "locks/build.txt", "builder @ https://example.invalid/builder.whl\n"
    )

    assert check_dependency_locks(tmp_path, _policy()) == []


def test_include_cycles_unsafe_paths_and_invalid_requirements_are_reported(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path, "config/requirements.txt", "-r nested.txt\ninvalid requirement line\n"
    )
    _write(tmp_path, "config/nested.txt", "-r requirements.txt\n")
    _write(tmp_path, "locks/base.txt", "\n")
    _write(tmp_path, "locks/build.txt", "\n")

    findings = check_dependency_locks(tmp_path, _policy())

    assert any(finding.message == "requirement include cycle" for finding in findings)
    assert any(
        finding.message == "invalid requirement declaration" for finding in findings
    )


def test_dependency_lock_policy_rejects_parent_paths() -> None:
    with pytest.raises(ValidationError):
        DependencyLockPolicy.model_validate(
            {"pairs": [{"input_file": "../outside.txt", "lock_file": "lock.txt"}]}
        )
