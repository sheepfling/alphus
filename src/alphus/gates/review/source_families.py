"""Lexical-only, advisory discovery of flat similarly named source families."""

from __future__ import annotations

import codecs
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from heapq import nsmallest
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from alphus.config import SourceFamilyPolicy as _SourceFamilyPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path

_SEPARATORS = re.compile(r"[_\-. ]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_LANGUAGE_EXTENSIONS = MappingProxyType(
    {
        ".py": "Python",
        ".pyi": "Python",
        ".c": "C",
        ".h": "C/C++",
        ".cc": "C++",
        ".hh": "C++",
        ".cpp": "C++",
        ".hpp": "C++",
        ".cxx": "C++",
        ".hxx": "C++",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".mjs": "JavaScript",
        ".cjs": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
    }
)
_C_CPP_HEADERS = frozenset({".h", ".hh", ".hpp", ".hxx"})
_C_CPP_IMPLEMENTATIONS = frozenset({".c", ".cc", ".cpp", ".cxx"})
_LINE_ENDINGS = frozenset("\n\v\f\x1c\x1d\x1e\x85\u2028\u2029")


def _tokens(stem: str) -> tuple[str, ...]:
    camel = _CAMEL_BOUNDARY.sub("_", stem)
    return tuple(
        token.casefold()
        for token in _SEPARATORS.split(camel)
        if token and not token.isdigit()
    )


def _language(path: PurePosixPath, policy: _SourceFamilyPolicy) -> str:
    for pattern, language in reversed(policy.path_language_overrides):
        if matches_path(path.as_posix(), pattern):
            return language
    return dict(policy.language_overrides).get(
        path.suffix.lower(), _LANGUAGE_EXTENSIONS.get(path.suffix.lower(), "other")
    )


def _line_count(path: Path) -> int:
    """Count physical text lines with bounded memory and strict UTF-8 decoding."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    line_count = 0
    line_has_content = False
    pending_carriage_return = False

    def count_breaks(text: str) -> None:
        nonlocal line_count, line_has_content, pending_carriage_return
        for character in text:
            if pending_carriage_return:
                line_count += 1
                pending_carriage_return = False
                line_has_content = False
                if character == "\n":
                    continue
            if character == "\r":
                pending_carriage_return = True
            elif character in _LINE_ENDINGS:
                line_count += 1
                line_has_content = False
            else:
                line_has_content = True

    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            count_breaks(decoder.decode(chunk))
    count_breaks(decoder.decode(b"", final=True))
    if pending_carriage_return or line_has_content:
        line_count += 1
    return line_count


def _logical_units(paths: Iterable[Path]) -> dict[Path, str]:
    """Pair C/C++ headers and implementations, keeping other suffixes distinct."""
    by_stem: dict[tuple[str, str], set[str]] = defaultdict(set)
    for relative in paths:
        posix = PurePosixPath(relative.as_posix())
        by_stem[(posix.parent.as_posix(), posix.stem)].add(posix.suffix.lower())

    paired_stems = {
        key
        for key, extensions in by_stem.items()
        if extensions & _C_CPP_HEADERS and extensions & _C_CPP_IMPLEMENTATIONS
    }
    result: dict[Path, str] = {}
    for relative in paths:
        posix = PurePosixPath(relative.as_posix())
        key = (posix.parent.as_posix(), posix.stem)
        if key in paired_stems and posix.suffix.lower() in (
            _C_CPP_HEADERS | _C_CPP_IMPLEMENTATIONS
        ):
            identity = f"c-family:{posix.stem}"
        else:
            identity = f"file:{posix.stem}:{posix.suffix.lower()}"
        result[relative] = identity
    return result


def _selected_paths(
    paths: Iterable[Path], policy: _SourceFamilyPolicy
) -> Iterable[Path]:
    for relative in paths:
        posix = PurePosixPath(relative.as_posix())
        if (
            posix.is_absolute()
            or ".." in posix.parts
            or posix.suffix.lower() not in policy.extensions
        ):
            continue
        name = posix.as_posix()
        if not any(matches_path(name, pattern) for pattern in policy.include):
            continue
        if any(matches_path(name, pattern) for pattern in policy.exclude):
            continue
        yield Path(*posix.parts)


def source_family_findings(
    root: Path, paths: Iterable[Path], policy: _SourceFamilyPolicy
) -> list[Finding]:
    """Return deterministic low-confidence candidates from the selected inventory."""
    checkout = root.resolve(strict=True)
    # Keep at most one sentinel beyond the configured inventory bound. Sorting the
    # bounded selection makes both processing and truncation deterministic.
    bounded = nsmallest(
        policy.max_files + 1,
        _selected_paths(paths, policy),
        key=lambda path: path.as_posix(),
    )
    inventory_truncated = len(bounded) > policy.max_files
    selected = bounded[: policy.max_files]
    incomplete_notes: list[str] = []
    rule_id = rule_tag(
        Scope.ANY, Framework.NONE, Category.MAINTAINABILITY, "flat-source-family"
    )
    if inventory_truncated:
        incomplete_notes.append(
            f"more than {policy.max_files} selected files were available and the "
            "inventory was limited"
        )

    logical_units = _logical_units(selected)
    groups: dict[tuple[str, ...], dict[str, set[Path]]] = defaultdict(
        lambda: defaultdict(set)
    )
    metadata: dict[Path, tuple[tuple[str, ...], str, int | None]] = {}
    unreadable: set[Path] = set()
    for relative in selected:
        posix = PurePosixPath(relative.as_posix())
        tokens = _tokens(posix.stem)
        if not tokens:
            continue
        metadata[relative] = (tokens, _language(posix, policy), None)
        try:
            source_path = (checkout / relative).resolve(strict=True)
            if not source_path.is_relative_to(checkout):
                raise OSError("source path resolves outside the selected checkout")
            lines = _line_count(source_path)
        except (OSError, UnicodeError):
            unreadable.add(relative)
        else:
            metadata[relative] = (tokens, _language(posix, policy), lines)

        # Prefixes are proper token prefixes. The minimum applies to token
        # characters, excluding separators; standalone numeric tokens are omitted.
        for stop in range(1, len(tokens)):
            prefix = tokens[:stop]
            if len("".join(prefix)) >= policy.min_prefix_characters:
                groups[(posix.parent.as_posix(), *prefix)][logical_units[relative]].add(
                    relative
                )

    if unreadable:
        incomplete_notes.append(
            f"{len(unreadable)} selected source files could not be read for line "
            "counts; their lexical names remain included"
        )

    candidates: list[tuple[str, tuple[str, ...], set[Path]]] = []
    for key, units in groups.items():
        if len(units) >= policy.min_family_files:
            directory, *prefix = key
            members = {path for unit_paths in units.values() for path in unit_paths}
            candidates.append((directory, tuple(prefix), members))

    # Assign each source to its deepest qualifying prefix. A nested family then
    # cannot be repeated in a broader finding; broader leftovers may still form a
    # separate candidate when they independently meet the configured threshold.
    candidates.sort(key=lambda row: (-len(row[1]), row[0], row[1]))
    retained: list[tuple[str, tuple[str, ...], set[Path]]] = []
    assigned: dict[str, set[Path]] = defaultdict(set)
    for directory, prefix, candidate_members in candidates:
        members = candidate_members - assigned[directory]
        units = {logical_units[path] for path in members}
        if len(units) < policy.min_family_files:
            continue
        retained.append((directory, prefix, members))
        assigned[directory].update(members)

    retained.sort(key=lambda row: (row[0], row[1]))
    incomplete_finding = (
        Finding(
            rule_id,
            ".",
            "Lexical source-family scan incomplete: "
            + "; ".join(incomplete_notes)
            + "; no clean result can be inferred from the partial evidence.",
            severity="warning",
        )
        if incomplete_notes
        else None
    )
    available_findings = len(retained) + (incomplete_finding is not None)
    output_truncated = available_findings > policy.max_findings
    if output_truncated and policy.max_findings == 1:
        incomplete_context = (
            " The scan was also incomplete: " + "; ".join(incomplete_notes) + "."
            if incomplete_notes
            else ""
        )
        return [
            Finding(
                rule_id,
                ".",
                f"Lexical source-family output truncated: {available_findings} findings "
                f"were available and only {policy.max_findings} may be returned."
                f"{incomplete_context}",
                severity="warning",
            )
        ]

    family_capacity = (
        policy.max_findings - 1 - (incomplete_finding is not None)
        if output_truncated
        else len(retained)
    )
    findings = [incomplete_finding] if incomplete_finding is not None else []
    for directory, prefix, members in retained[:family_capacity]:
        ordered = sorted(members, key=lambda path: path.as_posix())
        siblings = [
            path
            for path in selected
            if PurePosixPath(path.as_posix()).parent.as_posix() == directory
        ]
        language_counts = Counter(metadata[path][1] for path in ordered)
        known_line_counts = [
            line_count
            for path in ordered
            if (line_count := metadata[path][2]) is not None
        ]
        line_distribution = Counter(known_line_counts)
        distribution_rows = sorted(line_distribution.items())
        max_distribution_rows = min(policy.max_reported_members, 12)
        distribution_text = ", ".join(
            f"{count} file(s) at {line_count} lines"
            for line_count, count in distribution_rows[:max_distribution_rows]
        )
        if len(distribution_rows) > max_distribution_rows:
            distribution_text += (
                f", plus {len(distribution_rows) - max_distribution_rows} other "
                "distinct line counts"
            )
        line_context = (
            f"physical lines {min(known_line_counts)}–{max(known_line_counts)} "
            f"({len(known_line_counts)} counted; distribution: {distribution_text})"
            if known_line_counts
            else "physical-line counts unavailable"
        )
        if len(known_line_counts) < len(ordered):
            line_context += f"; {len(ordered) - len(known_line_counts)} unavailable"

        limit_by_extension = dict(policy.file_length_limits)
        limits = sorted(
            {
                (path.suffix.lower(), limit)
                for path in ordered
                if (limit := limit_by_extension.get(path.suffix.lower())) is not None
            }
        )
        limit_context = (
            "; configured file limits "
            + ", ".join(f"{extension}≤{limit} lines" for extension, limit in limits)
            if limits
            else "; no file limits configured"
        )
        prefix_text = "_".join(prefix)
        members_to_show = ordered[: policy.max_reported_members]
        member_details = ", ".join(
            f"{path.as_posix()} ({metadata[path][2]} lines)"
            if metadata[path][2] is not None
            else f"{path.as_posix()} (line count unavailable)"
            for path in members_to_show
        )
        member_context = (
            f"Members (showing {len(members_to_show)} of {len(ordered)}): "
            f"{member_details}"
        )
        if len(members_to_show) < len(ordered):
            member_context += "; member evidence truncated"

        language_text = ", ".join(
            f"{language}={count}" for language, count in sorted(language_counts.items())
        )
        sibling_basis = "selected sibling source files"
        if inventory_truncated:
            sibling_basis += " in the bounded inventory"
        include_text = ", ".join(policy.include)
        exclude_text = ", ".join(policy.exclude) or "(none)"
        extension_text = ", ".join(policy.extensions)
        override_text = ""
        if policy.language_overrides:
            override_text += "; extension language overrides " + ", ".join(
                f"{extension}={language}"
                for extension, language in policy.language_overrides
            )
        if policy.path_language_overrides:
            override_text += "; path language overrides (last match wins) " + ", ".join(
                f"{pattern}={language}"
                for pattern, language in policy.path_language_overrides
            )
        settings_text = (
            f"Settings: min_family_files={policy.min_family_files}, "
            f"min_prefix_characters={policy.min_prefix_characters}, "
            f"max_files={policy.max_files}, max_findings={policy.max_findings}, "
            f"max_reported_members={policy.max_reported_members}, "
            f"extensions={extension_text}, include={include_text}, "
            f"exclude={exclude_text}{override_text}. "
        )
        findings.append(
            Finding(
                rule_id,
                directory or ".",
                f"Family {prefix_text}_*: {len({logical_units[path] for path in ordered})} "
                f"logical units across {len(ordered)} physical files; {len(ordered)} of "
                f"{len(siblings)} {sibling_basis} "
                f"({len(ordered) / max(1, len(siblings)):.0%}); language mix "
                f"{language_text}; {line_context}{limit_context}. lexical-only, "
                "low-confidence advisory review candidate. "
                f"{settings_text}{member_context}. Coupling, imports, responsibility, "
                "and public surface not assessed; filename similarity alone does not establish an "
                "architectural problem.",
                severity="warning",
            )
        )

    if output_truncated:
        findings.append(
            Finding(
                rule_id,
                ".",
                f"Lexical source-family output truncated: {available_findings} findings "
                f"were available and only {policy.max_findings} may be returned."
                + (
                    " The scan was also incomplete; details are included in the "
                    "incomplete-scan finding."
                    if incomplete_finding is not None
                    else ""
                ),
                severity="warning",
            )
        )
    findings.sort(key=lambda finding: (finding.path, finding.message))
    return findings


def check_source_families(
    root: Path, paths: Iterable[Path], policy: _SourceFamilyPolicy
) -> list[Finding]:
    """Checker entry point for the optional source-family review rule."""
    return source_family_findings(root, paths, policy)
