"""Bounded lexical review candidates for benchmark-heavy Markdown sections."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from heapq import nsmallest
from pathlib import Path, PurePosixPath

from alphus.config import BenchmarkDocPolicy as _BenchmarkDocPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path

_DURATION = re.compile(
    r"(?<![\w.])\d+(?:[,_]\d{3})*(?:\.\d+)?\s*"
    r"(?:ns|nanoseconds?|µs|μs|us|microseconds?|ms|milliseconds?|"
    r"s|sec(?:onds?)?|minutes?|mins?)\b",
    re.IGNORECASE,
)
_THROUGHPUT = re.compile(
    r"(?<![\w.])\d+(?:[,_]\d{3})*(?:\.\d+)?\s*"
    r"(?:k|m|g)?\s*(?:ops?|operations?|req(?:uests?)?|items?|samples?)"
    r"\s*(?:/\s*s|per\s+second)\b",
    re.IGNORECASE,
)
_COMPARISON = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?\s*[×x]\s*"
    r"(?:faster|slower|speed.?up|improvement|throughput)\b|"
    r"(?:speed.?up|improvement|regression)\s+(?:of\s+)?"
    r"\d+(?:\.\d+)?\s*[×x%]",
    re.IGNORECASE,
)
_BENCHMARK_LANGUAGE = re.compile(
    r"\b(?:benchmarks?|benchmarking|throughput|performance comparison|"
    r"measured performance|performance test|microbenchmarks?)\b",
    re.IGNORECASE,
)
_METHOD_TERMS = re.compile(
    r"\b(?:method(?:ology)?|protocol|reproduc(?:e|ible|ibility)|command)\b",
    re.IGNORECASE,
)
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")


def _selected_paths(paths: Iterable[Path], policy: _BenchmarkDocPolicy) -> list[Path]:
    selected = (
        Path(*PurePosixPath(path.as_posix()).parts)
        for path in paths
        if not PurePosixPath(path.as_posix()).is_absolute()
        and ".." not in PurePosixPath(path.as_posix()).parts
        and PurePosixPath(path.as_posix()).suffix.lower() == ".md"
        and any(matches_path(path.as_posix(), pattern) for pattern in policy.include)
        and not any(
            matches_path(path.as_posix(), pattern)
            for pattern in (*policy.exclude, *policy.historical_report_patterns)
        )
    )
    return nsmallest(policy.max_files + 1, selected, key=Path.as_posix)


def _sections(lines: Sequence[str]) -> Iterable[tuple[str, int, str]]:
    title = "(document introduction)"
    start_line = 1
    body: list[str] = []
    fence: str | None = None
    fence_length = 0
    for line_number, line in enumerate(lines, start=1):
        fence_match = _FENCE.match(line)
        if fence is not None:
            if (
                fence_match
                and fence_match.group(1)[0] == fence
                and len(fence_match.group(1)) >= fence_length
            ):
                fence = None
                fence_length = 0
            continue
        if fence_match:
            fence = fence_match.group(1)[0]
            fence_length = len(fence_match.group(1))
            continue
        heading = _HEADING.match(line)
        if heading:
            if body:
                yield title, start_line, "\n".join(body)
            title = heading.group(2).strip()
            start_line = line_number
            body = []
        else:
            body.append(line)
    if body:
        yield title, start_line, "\n".join(body)


def _measurement_count(text: str) -> int:
    return (
        len(_DURATION.findall(text))
        + len(_THROUGHPUT.findall(text))
        + len(_COMPARISON.findall(text))
    )


def _reference_key(label: str) -> str:
    return " ".join(label.split()).casefold()


def _reference_definition(line: str) -> tuple[str, str, bool] | None:
    indentation = len(line) - len(line.lstrip(" \t"))
    if indentation > 3:
        return None
    content = line[indentation:]
    if not content.startswith("["):
        return None
    label_end = content.find("]", 1)
    if label_end <= 1 or label_end + 1 >= len(content) or content[label_end + 1] != ":":
        return None
    destination = content[label_end + 2 :].lstrip(" \t")
    if destination.startswith("<"):
        target_end = destination.find(">", 1)
        if target_end <= 1:
            return None
        target = destination[1:target_end]
    else:
        target = destination.split(None, 1)[0] if destination else ""
    if not target:
        return None
    return content[1:label_end], target, bool(_METHOD_TERMS.search(target))


def _method_link_definitions(text: str) -> dict[str, tuple[str, bool]]:
    definitions: dict[str, tuple[str, bool]] = {}
    for line in text.splitlines():
        definition = _reference_definition(line)
        if definition is not None:
            label, target, has_method_term = definition
            definitions[_reference_key(label)] = (target, has_method_term)
    return definitions


def _has_method_link(text: str, definitions: Mapping[str, tuple[str, bool]]) -> bool:
    lines = text.splitlines()
    text = "\n".join(line for line in lines if _reference_definition(line) is None)
    label_start: int | None = None
    reference_primary: str | None = None
    pending_label: tuple[str, int] | None = None
    inline_link: tuple[str, int, int] | None = None
    escaped = False

    for index, character in enumerate(text):
        escaped_character = escaped
        if character == "\\":
            escaped = not escaped
            continue
        escaped = False
        if character in "\r\n":
            escaped_character = False

        if inline_link is not None:
            label, target_start, depth = inline_link
            if escaped_character:
                continue
            if character == "(":
                inline_link = (label, target_start, depth + 1)
            elif character == ")":
                depth -= 1
                if depth == 0:
                    if _METHOD_TERMS.search(label) or _METHOD_TERMS.search(
                        text[target_start:index]
                    ):
                        return True
                    inline_link = None
                else:
                    inline_link = (label, target_start, depth)
            continue

        if pending_label is not None and pending_label[1] + 1 == index:
            if character == "[" and not escaped_character:
                reference_primary = pending_label[0]
                label_start = index + 1
                pending_label = None
                continue
            elif character == "(" and not escaped_character:
                inline_link = (pending_label[0], index + 1, 1)
                pending_label = None
                continue
            else:
                definition = definitions.get(_reference_key(pending_label[0]))
                if _METHOD_TERMS.search(pending_label[0]) or (
                    definition is not None and definition[1]
                ):
                    return True
            pending_label = None

        if escaped_character:
            continue
        if character == "[":
            label_start = index + 1
        elif character == "]":
            if label_start is not None:
                label = text[label_start:index]
                label_start = None
                if reference_primary is not None:
                    reference = label or reference_primary
                    definition = definitions.get(_reference_key(reference))
                    if (
                        _METHOD_TERMS.search(reference_primary)
                        or _METHOD_TERMS.search(label)
                        or (definition is not None and definition[1])
                    ):
                        return True
                    reference_primary = None
                else:
                    pending_label = (label, index)
        elif label_start is None and character not in " \t\r\n":
            reference_primary = None
    if pending_label is not None:
        definition = definitions.get(_reference_key(pending_label[0]))
        if _METHOD_TERMS.search(pending_label[0]) or (
            definition is not None and definition[1]
        ):
            return True
    return False


def benchmark_doc_findings(
    root: Path, paths: Iterable[Path], policy: _BenchmarkDocPolicy
) -> list[Finding]:
    """Return section-level review candidates without evaluating claims."""
    checkout = root.resolve(strict=True)
    selected = _selected_paths(paths, policy)
    truncated_inventory = len(selected) > policy.max_files
    findings: list[Finding] = []
    exceptions = {(item.path, item.section) for item in policy.exceptions}
    rule_id = rule_tag(
        Scope.MARKDOWN,
        Framework.NONE,
        Category.MAINTAINABILITY,
        "brittle-benchmark-prose",
    )

    def record(finding: Finding) -> bool:
        findings.append(finding)
        if len(findings) <= policy.max_findings:
            return False
        del findings[policy.max_findings - 1 :]
        findings.append(
            Finding(
                rule_id,
                ".",
                f"Findings or coverage status exceeded max_findings={policy.max_findings}; "
                "some selected scope is incomplete.",
                severity="info",
            )
        )
        return True

    for relative in selected[: policy.max_files]:
        relative_name = relative.as_posix()
        try:
            source = (checkout / relative).resolve(strict=True)
            if not source.is_relative_to(checkout):
                raise OSError("selected Markdown path resolves outside the checkout")
            with source.open("rb") as stream:
                raw = stream.read(policy.max_file_bytes + 1)
            if len(raw) > policy.max_file_bytes:
                if record(
                    Finding(
                        rule_id,
                        relative_name,
                        f"Selected Markdown file exceeds max_file_bytes={policy.max_file_bytes}; "
                        "benchmark prose was not analyzed, so this scope is incomplete.",
                        severity="info",
                    )
                ):
                    return findings
                continue
            text = raw.decode("utf-8")
        except (OSError, UnicodeError):
            if record(
                Finding(
                    rule_id,
                    relative_name,
                    "Selected Markdown file could not be read as UTF-8; this scope is incomplete.",
                    severity="warning",
                )
            ):
                return findings
            continue

        sections = list(_sections(text.splitlines()))
        visible_document = "\n".join(body for _, _, body in sections)
        method_definitions = _method_link_definitions(visible_document)
        for section, line, body in sections:
            if (relative_name, section) in exceptions:
                continue
            section_text = f"{section}\n{body}"
            measurements = _measurement_count(section_text)
            if (
                measurements < policy.min_measurements
                or not _BENCHMARK_LANGUAGE.search(section_text)
                or _has_method_link(section_text, method_definitions)
            ):
                continue
            if record(
                Finding(
                    rule_id,
                    relative_name,
                    f"Possible benchmark-heavy prose in section '{section}': "
                    f"{measurements} timing, throughput, or comparison expressions. "
                    "Review candidate only; freshness, correctness, and suitability "
                    "were not assessed. Consider keeping a concise workload and "
                    "reproducible command here, with detailed measurements in a "
                    "dated, maintained report when useful.",
                    line=line,
                    severity="warning",
                )
            ):
                return findings

    if truncated_inventory:
        record(
            Finding(
                rule_id,
                ".",
                f"Selected Markdown inventory exceeded max_files={policy.max_files}; "
                "only the lexically first files were analyzed, so this scope is incomplete.",
                severity="info",
            )
        )
    return findings


def check_benchmark_docs(
    root: Path, paths: Sequence[Path], policy: _BenchmarkDocPolicy
) -> list[Finding]:
    """Adapt the benchmark documentation scanner to the built-in runner contract."""
    return benchmark_doc_findings(root, paths, policy)
