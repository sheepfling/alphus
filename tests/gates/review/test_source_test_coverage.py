"""Synthetic contracts for explicit source-to-test coverage evidence."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from alphus.contracts.findings import Finding
from alphus.gates.review.source_test_coverage import check_source_test_coverage
from alphus.policy.source_test_coverage import (
    SourceTestCoveragePolicy,
    SourceTestRelationship,
)


def _commit_checkout(root: Path, files: dict[str, str]) -> str:
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "coverage@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Coverage Test"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_evidence(
    root: Path,
    revision: str,
    tests: dict[str, dict[str, object]],
    *,
    complete: bool = True,
    evidence_revision: str | None = None,
) -> None:
    path = root / "build/source-test-coverage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "alphus.source-test-coverage",
                "schema_version": 1,
                "revision": evidence_revision or revision,
                "complete": complete,
                "tests": tests,
            }
        ),
        encoding="utf-8",
    )


def _messages(findings: list[Finding]) -> list[str]:
    return [finding.message for finding in findings]


def test_unmapped_matching_filename_stays_unknown(tmp_path: Path) -> None:
    _commit_checkout(
        tmp_path,
        {
            "src/payments.py": "VALUE = 1\n",
            "tests/test_payments.py": "def test_payments(): pass\n",
        },
    )
    findings = check_source_test_coverage(tmp_path, (), SourceTestCoveragePolicy())

    assert len(findings) == 1
    assert "[coverage:unknown]" in findings[0].message
    assert "no tests are inferred from file names" in findings[0].message
    assert "missing" not in findings[0].message


def test_declared_but_absent_test_is_missing_without_basename_fallback(
    tmp_path: Path,
) -> None:
    _commit_checkout(
        tmp_path,
        {
            "src/invoice.py": "VALUE = 1\n",
            "tests/test_invoice.py": "def test_invoice(): pass\n",
        },
    )
    policy = SourceTestCoveragePolicy(
        relationships=(
            SourceTestRelationship(
                source="src/invoice.py",
                tests=("tests/integration/invoice_contract.py",),
            ),
        )
    )

    findings = check_source_test_coverage(tmp_path, (), policy)
    messages = _messages(findings)

    assert any("[coverage:missing]" in message for message in messages)
    assert any(
        "tests/integration/invoice_contract.py does not exist" in message
        for message in messages
    )
    assert all("tests/test_invoice.py" not in message for message in messages)


def test_integration_only_relationship_is_checked(tmp_path: Path) -> None:
    revision = _commit_checkout(
        tmp_path,
        {
            "src/api.py": "def handle(): return 1\n",
            "tests/integration/api_contract.py": "def test_api_contract(): pass\n",
        },
    )
    _write_evidence(
        tmp_path,
        revision,
        {
            "tests/integration/api_contract.py": {
                "outcome": "passed",
                "observed_sources": ["src/api.py"],
            }
        },
    )
    policy = SourceTestCoveragePolicy(
        relationships=(
            SourceTestRelationship(
                source="src/api.py",
                tests=("tests/integration/api_contract.py",),
            ),
        ),
        evidence_file="build/source-test-coverage.json",
    )

    findings = check_source_test_coverage(tmp_path, (), policy)

    assert any("[coverage:checked]" in item.message for item in findings)
    assert any("1 relationship(s) checked" in item.message for item in findings)


def test_shared_test_can_cover_multiple_sources_and_multiple_tests_can_cover_one(
    tmp_path: Path,
) -> None:
    revision = _commit_checkout(
        tmp_path,
        {
            "src/api.py": "VALUE = 1\n",
            "src/models.py": "VALUE = 2\n",
            "tests/unit/test_api.py": "def test_api(): pass\n",
            "tests/integration/test_contract.py": "def test_contract(): pass\n",
        },
    )
    _write_evidence(
        tmp_path,
        revision,
        {
            "tests/unit/test_api.py": {
                "outcome": "passed",
                "observed_sources": ["src/api.py"],
            },
            "tests/integration/test_contract.py": {
                "outcome": "passed",
                "observed_sources": ["src/api.py", "src/models.py"],
            },
        },
    )
    policy = SourceTestCoveragePolicy(
        relationships=(
            SourceTestRelationship(
                source="src/api.py",
                tests=(
                    "tests/unit/test_api.py",
                    "tests/integration/test_contract.py",
                ),
            ),
            SourceTestRelationship(
                source="src/models.py",
                tests=("tests/integration/test_contract.py",),
            ),
        ),
        evidence_file="build/source-test-coverage.json",
    )

    findings = check_source_test_coverage(tmp_path, (), policy)

    checked = [item for item in findings if "[coverage:checked]" in item.message]
    assert len(checked) == 3
    assert sum(item.path == "src/api.py" for item in checked) == 2
    assert sum(item.path == "src/models.py" for item in checked) == 1


def test_generated_and_reasoned_exclusions_are_reported_not_counted_as_checked(
    tmp_path: Path,
) -> None:
    _commit_checkout(tmp_path, {"README.md": "# fixture\n"})
    policy = SourceTestCoveragePolicy(
        relationships=(
            SourceTestRelationship(source="src/generated/api.py", generated=True),
            SourceTestRelationship(
                source="src/vendor.py",
                exclusion_reason="This vendored module is maintained by another project.",
            ),
        )
    )

    findings = check_source_test_coverage(tmp_path, (), policy)

    excluded = [item for item in findings if "[coverage:excluded]" in item.message]
    assert len(excluded) == 2
    assert any("generated" in item.message for item in excluded)
    assert any("maintained by another project" in item.message for item in excluded)
    assert any("2 explicitly excluded" in item.message for item in findings)


def test_stale_revision_and_mismatched_source_evidence_remain_unverified(
    tmp_path: Path,
) -> None:
    revision = _commit_checkout(
        tmp_path,
        {
            "src/service.py": "def run(): return 1\\n",
            "tests/integration/test_service.py": "def test_service(): pass\\n",
        },
    )
    tests = {
        "tests/integration/test_service.py": {
            "outcome": "passed",
            "observed_sources": ["src/other_service.py"],
        }
    }
    policy = SourceTestCoveragePolicy(
        relationships=(
            SourceTestRelationship(
                source="src/service.py",
                tests=("tests/integration/test_service.py",),
            ),
        ),
        evidence_file="build/source-test-coverage.json",
    )

    _write_evidence(tmp_path, revision, tests)
    mismatched = check_source_test_coverage(tmp_path, (), policy)
    assert any(
        "did not report this source" in item.message for item in mismatched
    )
    assert any("[coverage:unverified]" in item.message for item in mismatched)
    assert not any("[coverage:checked]" in item.message for item in mismatched)

    _write_evidence(tmp_path, revision, tests, evidence_revision="0" * 40)
    stale = check_source_test_coverage(tmp_path, (), policy)
    assert any("evidence is stale" in item.message for item in stale)
    assert any("[coverage:unverified]" in item.message for item in stale)
    assert not any("[coverage:checked]" in item.message for item in stale)

def test_absent_execution_artifact_is_unverified_not_clean(tmp_path: Path) -> None:
    _commit_checkout(
        tmp_path,
        {
            "src/worker.py": "def run(): return 1\\n",
            "tests/test_worker.py": "def test_worker(): pass\\n",
        },
    )
    policy = SourceTestCoveragePolicy(
        relationships=(
            SourceTestRelationship(
                source="src/worker.py", tests=("tests/test_worker.py",)
            ),
        )
    )

    findings = check_source_test_coverage(tmp_path, (), policy)

    assert any("no evidence_file is configured" in item.message for item in findings)
    assert any("[coverage:unverified]" in item.message for item in findings)
    assert not any("[coverage:missing]" in item.message for item in findings)


def test_policy_rejects_unsafe_relationship_paths() -> None:
    try:
        SourceTestCoveragePolicy(
            relationships=(SourceTestRelationship(source="../src/private.py"),)
        )
    except ValueError:
        return
    raise AssertionError("unsafe relative paths must be rejected")


def test_missing_and_skipped_execution_rows_are_unknown_not_missing_tests(
    tmp_path: Path,
) -> None:
    revision = _commit_checkout(
        tmp_path,
        {
            "src/a.py": "VALUE = 1\n",
            "src/b.py": "VALUE = 2\n",
            "tests/test_a.py": "def test_a(): pass\n",
            "tests/test_b.py": "def test_b(): pass\n",
        },
    )
    _write_evidence(
        tmp_path,
        revision,
        {
            "tests/test_a.py": {
                "outcome": "skipped",
                "observed_sources": [],
            }
        },
        complete=False,
    )
    policy = SourceTestCoveragePolicy(
        relationships=(
            SourceTestRelationship(source="src/a.py", tests=("tests/test_a.py",)),
            SourceTestRelationship(source="src/b.py", tests=("tests/test_b.py",)),
        ),
        evidence_file="build/source-test-coverage.json",
    )

    findings = check_source_test_coverage(tmp_path, (), policy)

    assert sum("[coverage:unverified]" in item.message for item in findings) >= 2
    assert any("partial evidence has no row" in item.message for item in findings)
    assert any("was skipped" in item.message for item in findings)
    assert not any("[coverage:missing]" in item.message for item in findings)


def test_failed_test_execution_can_confirm_relationship_without_claiming_quality(
    tmp_path: Path,
) -> None:
    revision = _commit_checkout(
        tmp_path,
        {
            "src/failing.py": "def run(): return 1\n",
            "tests/test_failing.py": "def test_failing(): assert False\n",
        },
    )
    _write_evidence(
        tmp_path,
        revision,
        {
            "tests/test_failing.py": {
                "outcome": "failed",
                "observed_sources": ["src/failing.py"],
            }
        },
    )
    policy = SourceTestCoveragePolicy(
        relationships=(
            SourceTestRelationship(
                source="src/failing.py", tests=("tests/test_failing.py",)
            ),
        ),
        evidence_file="build/source-test-coverage.json",
    )

    findings = check_source_test_coverage(tmp_path, (), policy)

    assert any("[coverage:checked]" in item.message for item in findings)
    assert any("failure remains a test result" in item.message for item in findings)
    assert any(
        "Test correctness and quality were not assessed" in item.message
        for item in findings
    )
