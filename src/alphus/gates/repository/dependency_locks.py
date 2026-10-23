"""Verify declared Python requirements against exact reusable lock inputs."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from alphus.config import DependencyLockPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import rule_tag
from alphus.support.data_access import contained_file


@dataclass(frozen=True, slots=True)
class RequirementLoad:
    """Requirements parsed from a lock input and any source findings."""

    requirements: Mapping[str, Requirement]
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
            (
                Finding(
                    rule_id=rule_tag(
                        "repository", "none", "dependencies", "lock-include-cycle"
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
            (
                Finding(
                    rule_id=rule_tag(
                        "repository", "none", "dependencies", "lock-input-missing"
                    ),
                    path=relative,
                    message="requirement file is missing or resolves outside the repository",
                ),
            ),
        )
    result: dict[str, Requirement] = {}
    findings: list[Finding] = []
    current = active | {relative}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
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
                            "repository", "none", "dependencies", "lock-include-invalid"
                        ),
                        path=relative,
                        line=line_number,
                        message=f"requirement include {include_value!r} is unsafe or missing",
                    )
                )
                continue
            nested_load = _load_requirements(root, nested, current)
            result.update(nested_load.requirements)
            findings.extend(nested_load.findings)
            continue
        try:
            requirement = Requirement(value)
        except InvalidRequirement:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        "repository", "none", "dependencies", "requirement-invalid"
                    ),
                    path=relative,
                    line=line_number,
                    message="invalid requirement declaration",
                )
            )
            continue
        result[canonicalize_name(requirement.name)] = requirement
    return RequirementLoad(MappingProxyType(result), tuple(findings))


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
                        "repository",
                        "none",
                        "dependencies",
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
    findings.extend(_exact_pin_findings(lock_file, pinned))
    for name, requirement in declared.items():
        resolved = pinned.get(name)
        if resolved is None:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        "repository", "none", "dependencies", "requirement-unlocked"
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
                            "repository", "none", "dependencies", "lock-source-mismatch"
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
                        "repository",
                        "none",
                        "dependencies",
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
        findings.extend(_exact_pin_findings(lock_file, load.requirements))
    return findings
