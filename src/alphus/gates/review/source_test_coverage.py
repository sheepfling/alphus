"""Advisory audit of explicitly declared source-to-test evidence."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.base import validate_single_path
from alphus.policy.source_test_coverage import (
    SourceTestCoveragePolicy as _SourceTestCoveragePolicy,
)
from alphus.support.data_access import contained_file
from alphus.support.git import git_value
from alphus.support.source_text import read_utf8_text

_RULE_ID = rule_tag(
    Scope.REPOSITORY, Framework.NONE, Category.TESTING, "source-test-coverage"
)
_ARTIFACT_SCHEMA = "alphus.source-test-coverage"
_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_OUTCOMES = frozenset({"passed", "failed", "skipped", "not_selected"})

EvidenceStatus = Literal["current", "partial", "unavailable", "stale", "invalid"]


@dataclass(frozen=True, slots=True)
class _TestObservation:
    outcome: str
    observed_sources: frozenset[str]


@dataclass(frozen=True, slots=True)
class _CoverageEvidence:
    status: EvidenceStatus
    reason: str
    complete: bool
    tests: Mapping[str, _TestObservation]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("evidence contains a duplicate JSON object key")
        result[key] = value
    return result


def _exact_keys(
    value: Mapping[str, object], expected: frozenset[str], context: str
) -> None:
    if frozenset(value) != expected:
        raise ValueError(f"{context} has unsupported or missing fields")


def _artifact_path(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a repository-relative file path")
    checked = validate_single_path(value, context)
    if checked == ".":
        raise ValueError(f"{context} must name a file")
    return checked


def _path_state(
    root: Path, relative: str
) -> Literal["present", "missing", "untrusted"]:
    if contained_file(root, relative) is not None:
        return "present"
    candidate = root / relative
    try:
        return "untrusted" if candidate.exists() else "missing"
    except (OSError, ValueError):
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
    evidence_path = contained_file(root, policy.evidence_file)
    if evidence_path is None:
        return _unavailable(
            "the configured evidence file is missing or is not safely contained"
        )
    if current_revision is None or not _REVISION.fullmatch(current_revision):
        return _unavailable("the checkout revision could not be established")
    try:
        decoded = json.loads(
            read_utf8_text(evidence_path), object_pairs_hook=_unique_object
        )
    except (OSError, UnicodeError, ValueError, TypeError):
        return _unavailable(
            "the configured evidence file is unreadable or invalid JSON",
            status="invalid",
        )
    if not isinstance(decoded, dict):
        return _unavailable(
            "the evidence document must be a JSON object", status="invalid"
        )
    try:
        _exact_keys(
            decoded,
            frozenset({"schema", "schema_version", "revision", "complete", "tests"}),
            "evidence document",
        )
        if decoded["schema"] != _ARTIFACT_SCHEMA:
            raise ValueError("evidence schema identifier is unsupported")
        if type(decoded["schema_version"]) is not int or decoded["schema_version"] != 1:
            raise ValueError("evidence schema version is unsupported")
        revision = decoded["revision"]
        if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
            raise ValueError("evidence revision must be a full Git commit SHA")
        complete = decoded["complete"]
        if type(complete) is not bool:
            raise ValueError("evidence complete must be a boolean")
        raw_tests = decoded["tests"]
        if not isinstance(raw_tests, dict):
            raise ValueError("evidence tests must be an object")
        observations: dict[str, _TestObservation] = {}
        for raw_test, raw_observation in raw_tests.items():
            test_path = _artifact_path(raw_test, "evidence test path")
            if not isinstance(raw_observation, dict):
                raise ValueError("each test observation must be an object")
            _exact_keys(
                raw_observation,
                frozenset({"outcome", "observed_sources"}),
                "test observation",
            )
            outcome = raw_observation["outcome"]
            if not isinstance(outcome, str) or outcome not in _OUTCOMES:
                raise ValueError("test outcome is unsupported")
            raw_sources = raw_observation["observed_sources"]
            if not isinstance(raw_sources, list):
                raise ValueError("observed_sources must be an array")
            observed_sources = tuple(
                _artifact_path(source, "observed source path")
                for source in raw_sources
            )
            if len(observed_sources) != len(set(observed_sources)):
                raise ValueError("observed source paths must be unique per test")
            observations[test_path] = _TestObservation(
                outcome, frozenset(observed_sources)
            )
    except (TypeError, ValueError):
        return _unavailable(
            "the evidence document does not match the supported schema",
            status="invalid",
        )
    if revision != current_revision:
        return _unavailable(
            "the evidence revision does not match the current checkout",
            status="stale",
        )
    return _CoverageEvidence(
        "current" if complete else "partial",
        "current revision-matched execution evidence"
        if complete
        else "revision-matched evidence is marked partial",
        complete,
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
    state = "complete" if not unverified and not missing else "incomplete"
    record(
        ".",
        state,
        f"{checked} relationship(s) checked, {unverified} unverified, "
        f"{missing} missing, {excluded} explicitly excluded; evidence is "
        f"{evidence.status}. Test correctness and quality were not assessed",
    )
    return findings
