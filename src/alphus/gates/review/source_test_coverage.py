"""Advisory audit of explicitly declared source-to-test evidence."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.base import StrictModel, require_unique, validate_single_path
from alphus.policy.source_test_coverage import (
    SourceTestCoveragePolicy as _SourceTestCoveragePolicy,
)
from alphus.support.data_access import JsonValue, contained_file
from alphus.support.git import git_value, run_git
from alphus.support.source_text import read_utf8_text

ALPHUS_MORPHOLOGY = {
    "selector": "source-test-coverage",
    "finding_ids": ("alphus/repository/none/testing/source-test-coverage",),
    "concern": "declared-source-test-evidence",
    "claim": "Declared source-to-test relationships agree with revision-matched test-execution evidence.",
    "mechanisms": ("exact-rule",),
    "inspected_scope": (
        "declared-source-test-relationships",
        "revision-matched-test-evidence",
    ),
    "languages_formats": ("repository", "json", "toml"),
    "evidence_kinds": (
        "declared-relationship",
        "revision-matched-execution-status",
        "tracked-paths",
    ),
    "evaluation_maturity": "synthetic-only",
}


_RULE_ID = rule_tag(
    Scope.REPOSITORY, Framework.NONE, Category.TESTING, "source-test-coverage"
)
_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")

EvidenceStatus = Literal["current", "partial", "unavailable", "stale", "invalid"]
TestOutcome = Literal["passed", "failed", "skipped", "not_selected"]


@dataclass(frozen=True, slots=True)
class _TestObservation:
    outcome: TestOutcome
    observed_sources: frozenset[str]


@dataclass(frozen=True, slots=True)
class _CoverageEvidence:
    status: EvidenceStatus
    reason: str
    complete: bool
    tests: dict[str, _TestObservation]


class _EvidenceObservation(StrictModel):
    outcome: TestOutcome
    observed_sources: tuple[str, ...]

    @field_validator("observed_sources")
    @classmethod
    def validate_observed_sources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(
            _artifact_path(value, "observed source path") for value in values
        )
        require_unique(checked, "observed source paths must be unique per test")
        return checked


class _EvidenceDocument(StrictModel):
    schema_id: Annotated[
        Literal["alphus.source-test-coverage"], Field(validation_alias="schema")
    ]
    schema_version: int
    revision: str
    complete: bool
    tests: dict[str, _EvidenceObservation]

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("evidence schema version is unsupported")
        return value

    @field_validator("revision")
    @classmethod
    def validate_revision(cls, value: str) -> str:
        if not _REVISION.fullmatch(value):
            raise ValueError("evidence revision must be a full Git commit SHA")
        return value

    @field_validator("tests")
    @classmethod
    def validate_test_paths(
        cls, tests: Mapping[str, _EvidenceObservation]
    ) -> dict[str, _EvidenceObservation]:
        for test_path in tests:
            _artifact_path(test_path, "evidence test path")
        return dict(tests)


def _unique_object(pairs: Iterable[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("evidence contains a duplicate JSON object key")
        result[key] = value
    return result


def _artifact_path(value: str, context: str) -> str:
    checked = validate_single_path(value, context)
    if checked == "." or any(
        ord(character) < 32 or ord(character) == 127 for character in checked
    ):
        raise ValueError(f"{context} must name a repository-relative file path")
    return checked


def _tracked_file_matches_head(root: Path, relative: str) -> bool:
    """Require audited source/test files to match the evidence checkout."""
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
        if resolved != candidate:
            return False
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return False
    pathspec = f":(literal){relative}"
    try:
        tracked = run_git(root, "ls-files", "-v", "--error-unmatch", "--", pathspec)
        if tracked.returncode != 0 or not tracked.stdout.startswith(b"H "):
            return False
        staged = run_git(root, "diff", "--cached", "--quiet", "HEAD", "--", pathspec)
        unstaged = run_git(root, "diff", "--quiet", "--", pathspec)
    except OSError:
        return False
    return staged.returncode == 0 and unstaged.returncode == 0


def _path_state(
    root: Path, relative: str
) -> Literal["present", "missing", "untrusted"]:
    try:
        if contained_file(root, relative) is not None:
            return "present"
        candidate = root / relative
        return "untrusted" if candidate.exists() else "missing"
    except (OSError, RuntimeError, ValueError):
        return "untrusted"


def _unavailable(
    reason: str, *, status: EvidenceStatus = "unavailable"
) -> _CoverageEvidence:
    return _CoverageEvidence(status, reason, False, {})


def _load_evidence(
    root: Path,
    policy: _SourceTestCoveragePolicy,
    current_revision: str | None,
) -> _CoverageEvidence:
    if policy.evidence_file is None:
        return _unavailable("no evidence_file is configured")
    try:
        evidence_path = contained_file(root, policy.evidence_file)
    except (OSError, RuntimeError, ValueError):
        evidence_path = None
    if evidence_path is None:
        return _unavailable(
            "the configured evidence file is missing or is not safely contained"
        )
    if current_revision is None or not _REVISION.fullmatch(current_revision):
        return _unavailable("the checkout revision could not be established")
    try:
        text = read_utf8_text(evidence_path)
        # Reject duplicate keys before the named strict model validates the payload.
        decoded = json.JSONDecoder(object_pairs_hook=_unique_object).decode(text)
        artifact = _EvidenceDocument.model_validate(decoded)
    except (OSError, UnicodeError, ValueError, TypeError):
        return _unavailable(
            "the evidence document is unreadable, invalid JSON, or does not match "
            "the supported schema",
            status="invalid",
        )
    if artifact.revision != current_revision:
        return _unavailable(
            "the evidence revision does not match the current checkout",
            status="stale",
        )
    observations = {
        test_path: _TestObservation(
            observation.outcome, frozenset(observation.observed_sources)
        )
        for test_path, observation in artifact.tests.items()
    }
    return _CoverageEvidence(
        "current" if artifact.complete else "partial",
        "current revision-matched execution evidence"
        if artifact.complete
        else "revision-matched evidence is marked partial",
        artifact.complete,
        observations,
    )


def _finding(path: str, status: str, detail: str) -> Finding:
    return Finding(
        rule_id=_RULE_ID,
        path=path,
        message=f"[coverage:{status}] {detail}",
        severity="info",
    )


def check_source_test_coverage(
    root: Path,
    _paths: object,
    policy: _SourceTestCoveragePolicy,
) -> list[Finding]:
    """Check only declared relationships; never guess from file names."""
    checkout = root.resolve(strict=True)
    if not policy.relationships:
        return [
            _finding(
                ".",
                "unknown",
                "no source-to-test relationships are declared; no tests are inferred "
                "from file names",
            )
        ]

    current_revision = git_value(checkout, "rev-parse", "HEAD")
    evidence = _load_evidence(checkout, policy, current_revision)
    findings: list[Finding] = []
    counts: Counter[str] = Counter()

    def record(path: str, status: str, detail: str) -> None:
        findings.append(_finding(path, status, detail))
        counts[status] += 1

    for relationship in sorted(policy.relationships, key=lambda item: item.source):
        source = relationship.source
        if relationship.generated:
            record(source, "excluded", "source is explicitly declared generated")
            continue
        if relationship.exclusion_reason is not None:
            record(
                source,
                "excluded",
                f"source is excluded by the caller: {relationship.exclusion_reason}",
            )
            continue
        source_state = _path_state(checkout, source)
        if source_state != "present":
            record(
                source,
                "unverified",
                "declared source is missing or outside the repository; the "
                "relationship may be stale",
            )
            continue
        if not _tracked_file_matches_head(checkout, source):
            record(
                source,
                "unverified",
                "declared source is symlinked, untracked, modified, or has "
                "index flags that hide changes; evidence freshness cannot be "
                "established",
            )
            continue
        if not relationship.tests:
            record(
                source,
                "missing",
                "the explicit source declaration lists no expected tests",
            )
            continue

        for test_path in sorted(relationship.tests):
            test_state = _path_state(checkout, test_path)
            if test_state == "missing":
                record(
                    source,
                    "missing",
                    f"declared test file {test_path} does not exist",
                )
                continue
            if test_state == "untrusted":
                record(
                    source,
                    "unverified",
                    f"declared test file {test_path} is not safely contained",
                )
                continue
            if not _tracked_file_matches_head(checkout, test_path):
                record(
                    source,
                    "unverified",
                    f"declared test file {test_path} is symlinked, untracked, "
                    "modified, or has index flags that hide changes; evidence "
                    "freshness cannot be established",
                )
                continue
            if evidence.status not in {"current", "partial"}:
                record(
                    source,
                    "unverified",
                    f"execution evidence is {evidence.status}: {evidence.reason}; "
                    f"relationship with {test_path} was not verified",
                )
                continue
            observation = evidence.tests.get(test_path)
            if observation is None:
                qualifier = (
                    "complete evidence has no row for"
                    if evidence.complete
                    else "partial evidence has no row for"
                )
                record(
                    source,
                    "unverified",
                    f"{qualifier} declared test {test_path}; this is missing "
                    "execution evidence, not proof that the test is absent",
                )
                continue
            if observation.outcome in {"skipped", "not_selected"}:
                record(
                    source,
                    "unverified",
                    f"declared test {test_path} was {observation.outcome}; "
                    "no executed source relationship was established",
                )
                continue
            if source not in observation.observed_sources:
                record(
                    source,
                    "unverified",
                    f"declared test {test_path} ran with outcome "
                    f"{observation.outcome} but did not report this source",
                )
                continue
            outcome_note = (
                "its failure remains a test result, not a coverage-contract verdict"
                if observation.outcome == "failed"
                else "its pass status is not evidence of assertion quality"
            )
            record(
                source,
                "checked",
                f"declared test {test_path} observed this source; {outcome_note}",
            )

    checked = counts["checked"]
    unverified = counts["unverified"]
    missing = counts["missing"]
    excluded = counts["excluded"]
    state = (
        "complete"
        if evidence.complete and not unverified and not missing
        else "incomplete"
    )
    record(
        ".",
        state,
        f"{checked} relationship(s) checked, {unverified} unverified, "
        f"{missing} missing, {excluded} explicitly excluded; evidence is "
        f"{evidence.status}. Test correctness and quality were not assessed",
    )
    return findings
