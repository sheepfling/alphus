"""Verify declared Python requirements against exact reusable lock inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import Specifier
from packaging.utils import canonicalize_name
from packaging.version import Version

from alphus.config import DependencyLockPolicy, QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.base import require_policy
from alphus.support.data_access import contained_file
from alphus.support.source_text import read_utf8_text

ALPHUS_CHECK: Final = (
    ("selector", "dependency-locks"),
    ("concern", "dependency-lock-consistency"),
    ("claim_kind", "condition"),
    (
        "claim",
        "Configured requirement declarations and lock entries are consistent "
        "under their declared version and source constraints.",
    ),
    ("mechanisms", ("exact-rule", "bounded-heuristic")),
    ("inspected_scope", ("repository", "requirement-files", "lock-files")),
    ("languages_formats", ("python-requirements", "pep508-metadata")),
    (
        "evidence_kinds",
        ("resolved-requirement", "version-specifier", "include-edge", "marker"),
    ),
    ("evaluation_maturity", "synthetic-only"),
    (
        "finding_tag_complaints",
        (
            "lock-include-cycle",
            "lock-input-missing",
            "requirement-pin-not-exact",
            "requirement-unlocked",
            "lock-include-invalid",
            "requirement-invalid",
            "duplicate-requirement-conflict",
            "duplicate-requirement-marker-uncertain",
            "lock-source-mismatch",
            "requirement-pin-unsatisfied",
        ),
    ),
    ("policy_field", "dependency_locks"),
    ("policy_model", "alphus.policy.repository.DependencyLockPolicy"),
    ("output_shape", "findings"),
    (
        "summary",
        "Checks consistency and pairing of configured dependency lockfiles.",
    ),
    (("applies_to", ("python", "javascript"))),
    (("domains", ())),
    ("requires_files", True),
    ("runner_module", "alphus.gates.repository.dependency_locks"),
    ("runner_name", "run_dependency_lock_gate"),
)


@dataclass(frozen=True, slots=True)
class RequirementDeclaration:
    """One parsed requirement with its source location retained."""

    source: str
    line: int
    requirement: Requirement


@dataclass(frozen=True, slots=True)
class _MarkerCondition:
    operator: str
    version: str


@dataclass(frozen=True, slots=True)
class RequirementLoad:
    """Requirements parsed from a lock input and any source findings."""

    requirements: Mapping[str, Requirement]
    declarations: tuple[RequirementDeclaration, ...]
    findings: tuple[Finding, ...]


def _include_path(root: Path, source: str, value: str) -> str | None:
    include = PurePosixPath(value)
    source_path = PurePosixPath(Path(source).as_posix())
    if not value or include.is_absolute() or "\\" in value:
        return None
    candidate = root.joinpath(*source_path.parent.parts, *include.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved.relative_to(root).as_posix()


def _load_requirements(
    root: Path, relative: str, active: AbstractSet[str] = frozenset()
) -> RequirementLoad:
    relative = Path(relative).as_posix()
    if relative in active:
        return RequirementLoad(
            MappingProxyType({}),
            (),
            (
                Finding(
                    rule_id=rule_tag(
                        Scope.REPOSITORY,
                        Framework.NONE,
                        Category.DEPENDENCIES,
                        "lock-include-cycle",
                    ),
                    path=relative,
                    message="requirement include cycle",
                ),
            ),
        )
    path = contained_file(root, relative)
    if path is None:
        return RequirementLoad(
            MappingProxyType({}),
            (),
            (
                Finding(
                    rule_id=rule_tag(
                        Scope.REPOSITORY,
                        Framework.NONE,
                        Category.DEPENDENCIES,
                        "lock-input-missing",
                    ),
                    path=relative,
                    message="requirement file is missing or resolves outside the repository",
                ),
            ),
        )
    result: dict[str, Requirement] = {}
    declarations: list[RequirementDeclaration] = []
    findings: list[Finding] = []
    current = active | {relative}
    for line_number, line in enumerate(read_utf8_text(path).splitlines(), 1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        include_value: str | None = None
        if value.startswith("-r "):
            include_value = value[3:].strip()
        elif value.startswith("--requirement "):
            include_value = value.removeprefix("--requirement ").strip()
        if include_value is not None:
            nested = _include_path(root, relative, include_value)
            if nested is None:
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            Scope.REPOSITORY,
                            Framework.NONE,
                            Category.DEPENDENCIES,
                            "lock-include-invalid",
                        ),
                        path=relative,
                        line=line_number,
                        message=f"requirement include {include_value!r} is unsafe or missing",
                    )
                )
                continue
            nested_load = _load_requirements(root, nested, current)
            result.update(nested_load.requirements)
            declarations.extend(nested_load.declarations)
            findings.extend(nested_load.findings)
            continue
        try:
            requirement = Requirement(value)
        except InvalidRequirement:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.REPOSITORY,
                        Framework.NONE,
                        Category.DEPENDENCIES,
                        "requirement-invalid",
                    ),
                    path=relative,
                    line=line_number,
                    message="invalid requirement declaration",
                )
            )
            continue
        name = canonicalize_name(requirement.name)
        declarations.append(RequirementDeclaration(relative, line_number, requirement))
        result[name] = requirement
    return RequirementLoad(
        MappingProxyType(result), tuple(declarations), tuple(findings)
    )


def _duplicate_exact_pin_findings(
    declarations: Sequence[RequirementDeclaration],
) -> list[Finding]:
    """Report exact conflicts and mark unresolved marker relationships as info."""
    seen: dict[str, list[RequirementDeclaration]] = {}
    findings: list[Finding] = []
    for declaration in declarations:
        requirement = declaration.requirement
        specifiers = tuple(requirement.specifier)
        if (
            requirement.url is not None
            or len(specifiers) != 1
            or specifiers[0].operator != "=="
            or "*" in specifiers[0].version
        ):
            continue
        name = canonicalize_name(requirement.name)
        prior_declarations = seen.setdefault(name, [])
        for previous in prior_declarations:
            previous_specifier = next(iter(previous.requirement.specifier))
            if _exact_pins_overlap(previous_specifier, specifiers[0]):
                continue
            if _marker_text(previous.requirement) == _marker_text(requirement):
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            Scope.REPOSITORY,
                            Framework.NONE,
                            Category.DEPENDENCIES,
                            "duplicate-requirement-conflict",
                        ),
                        path=declaration.source,
                        line=declaration.line,
                        message=(
                            f"{requirement.name} exact pin {specifiers[0].version} at "
                            f"{declaration.source}:{declaration.line} conflicts with "
                            f"{previous_specifier.version} at "
                            f"{previous.source}:{previous.line}; same environment marker"
                        ),
                    )
                )
            elif not _markers_provably_disjoint(previous.requirement, requirement):
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            Scope.REPOSITORY,
                            Framework.NONE,
                            Category.DEPENDENCIES,
                            "duplicate-requirement-marker-uncertain",
                        ),
                        path=declaration.source,
                        line=declaration.line,
                        severity="info",
                        message=(
                            f"{requirement.name} has differing exact pins at "
                            f"{previous.source}:{previous.line} and "
                            f"{declaration.source}:{declaration.line}; marker scopes "
                            "are not proven overlapping or disjoint"
                        ),
                    )
                )
        prior_declarations.append(declaration)
    return findings


def _exact_pins_overlap(left: Specifier, right: Specifier) -> bool:
    """Check whether two exact PEP 440 pins admit either pinned candidate."""
    left_version = Version(left.version)
    right_version = Version(right.version)
    return left.contains(right_version, prereleases=True) or right.contains(
        left_version, prereleases=True
    )


def _marker_text(requirement: Requirement) -> str | None:
    return str(requirement.marker) if requirement.marker is not None else None


def _markers_provably_disjoint(first: Requirement, second: Requirement) -> bool:
    """Prove only complementary simple Python-version half-open intervals."""
    first_marker = _marker_text(first)
    second_marker = _marker_text(second)
    if first_marker is None or second_marker is None:
        return False

    def condition(marker: str) -> _MarkerCondition | None:
        parts = marker.split()
        if len(parts) != 3 or parts[0] != "python_version":
            return None
        return _MarkerCondition(parts[1], parts[2].strip("'\""))

    left = condition(first_marker)
    right = condition(second_marker)
    if left is None or right is None or left.version != right.version:
        return False
    return (left.operator, right.operator) in {
        ("<", ">="),
        (">=", "<"),
        ("<=", ">"),
        (">", "<="),
    }


def _exact_pin_findings(
    path: str, requirements: Mapping[str, Requirement]
) -> list[Finding]:
    findings: list[Finding] = []
    for name, requirement in requirements.items():
        specifiers = tuple(requirement.specifier)
        if requirement.url is None and (
            len(specifiers) != 1
            or specifiers[0].operator != "=="
            or "*" in specifiers[0].version
        ):
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.REPOSITORY,
                        Framework.NONE,
                        Category.DEPENDENCIES,
                        "requirement-pin-not-exact",
                    ),
                    path=path,
                    message=f"{name} needs one exact version pin",
                )
            )
    return findings


def _pair_findings(root: Path, input_file: str, lock_file: str) -> list[Finding]:
    declared_load = _load_requirements(root, input_file)
    pinned_load = _load_requirements(root, lock_file)
    declared = declared_load.requirements
    pinned = pinned_load.requirements
    findings = [*declared_load.findings, *pinned_load.findings]
    findings.extend(_duplicate_exact_pin_findings(declared_load.declarations))
    findings.extend(_duplicate_exact_pin_findings(pinned_load.declarations))
    findings.extend(_exact_pin_findings(lock_file, pinned))
    for name, requirement in declared.items():
        resolved = pinned.get(name)
        if resolved is None:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.REPOSITORY,
                        Framework.NONE,
                        Category.DEPENDENCIES,
                        "requirement-unlocked",
                    ),
                    path=lock_file,
                    message=f"missing declared requirement {name} from {input_file}",
                )
            )
        elif requirement.url is not None:
            if resolved.url != requirement.url:
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            Scope.REPOSITORY,
                            Framework.NONE,
                            Category.DEPENDENCIES,
                            "lock-source-mismatch",
                        ),
                        path=lock_file,
                        message=f"{name} source differs from {input_file}",
                    )
                )
        elif resolved.url is not None or not any(
            pin.version in requirement.specifier for pin in resolved.specifier
        ):
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.REPOSITORY,
                        Framework.NONE,
                        Category.DEPENDENCIES,
                        "requirement-pin-unsatisfied",
                    ),
                    path=lock_file,
                    message=f"{name} pin does not satisfy {input_file}",
                )
            )
    return findings


def check_dependency_locks(root: Path, policy: DependencyLockPolicy) -> list[Finding]:
    """Check configured requirement/lock pairs and exact-pin-only lock files."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for pair in policy.pairs:
        findings.extend(_pair_findings(checkout, pair.input_file, pair.lock_file))
    for lock_file in policy.exact_pin_files:
        load = _load_requirements(checkout, lock_file)
        findings.extend(load.findings)
        findings.extend(_duplicate_exact_pin_findings(load.declarations))
        findings.extend(_exact_pin_findings(lock_file, load.requirements))
    return findings


def run_dependency_lock_gate(
    root: Path, _files: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Run the feature-owned dependency-lock check with its strict policy."""
    policy = require_policy(config.checks.dependency_locks, "dependency_locks")
    return check_dependency_locks(root, policy)
