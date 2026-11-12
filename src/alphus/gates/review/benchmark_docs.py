"""Bounded lexical review candidates for benchmark-heavy Markdown sections."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from heapq import nsmallest
from pathlib import Path, PurePosixPath
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import BenchmarkDocPolicy
from alphus.support.inventory import matches_path

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="benchmark-docs",
    policy_field="benchmark_docs",
    policy_model=BenchmarkDocPolicy,
    output_shape="findings",
    summary="Reviews benchmark documentation for required result context.",
    applies_to=("markdown", "benchmarking"),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="benchmark-docs",
    finding_ids=(
        RuleTag(
            Scope.MARKDOWN,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "brittle-benchmark-prose",
        ),
    ),
    concern="benchmark-reproducibility-context",
    claim_kind=ClaimKind.RISK,
    claim=(
        "Benchmark documentation may omit protocol or result context needed to "
        "reproduce or assess measurements."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("selected-markdown-files", "benchmark-sections"),
    languages_formats=("markdown",),
    evidence_kinds=("bounded-lexical-match", "heading-context", "document-location"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


_DURATION = re.compile(
    r"(?<![\w.])\d+(?:[,_]\d{3})*(?:\.\d+)?\s*"
    r"(?:ns|nanoseconds?|µs|μs|us|microseconds?|ms|milliseconds?|"
    r"s|sec(?:onds?)?|minutes?|mins?)\b",
    re.IGNORECASE,
)
_THROUGHPUT = re.compile(
    r"(?<![\w.])\d+(?:[,_]\d{3})*(?:\.\d+)?\s*"
    r"(?:(?:k|m|g)\s*)?(?:ops?|operations?|req(?:uests?)?|items?|samples?)"
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
_SETEXT_HEADING = re.compile(r"^\s{0,3}(=+|-+)\s*$")


def _selected_paths(paths: Iterable[Path], policy: BenchmarkDocPolicy) -> list[Path]:
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


def _sections(
    lines: Sequence[str],
) -> Iterable[tuple[str, int, str, tuple[str, ...]]]:
    title = "(document introduction)"
    start_line = 1
    body: list[str] = []
    heading_path: list[tuple[int, str]] = []
    fence: str | None = None
    fence_length = 0
    index = 0
    while index < len(lines):
        line_number = index + 1
        line = lines[index]
        fence_match = _FENCE.match(line)
        if fence is not None:
            if (
                fence_match
                and fence_match.group(1)[0] == fence
                and len(fence_match.group(1)) >= fence_length
            ):
                fence = None
                fence_length = 0
            index += 1
            continue
        if fence_match:
            fence = fence_match.group(1)[0]
            fence_length = len(fence_match.group(1))
            index += 1
            continue
        heading = _HEADING.match(line)
        setext_heading = (
            _SETEXT_HEADING.match(lines[index + 1])
            if index + 1 < len(lines) and line.strip()
            else None
        )
        if heading or setext_heading:
            if body:
                context = tuple(part for _, part in heading_path) or (title,)
                yield title, start_line, "\n".join(body), context
            if heading:
                level = len(heading.group(1))
                title = heading.group(2).strip()
                consumed = 1
            else:
                assert setext_heading is not None
                level = 1 if setext_heading.group(1).startswith("=") else 2
                title = line.strip()
                consumed = 2
            while heading_path and heading_path[-1][0] >= level:
                heading_path.pop()
            heading_path.append((level, title))
            start_line = line_number
            body = []
            index += consumed
        else:
            body.append(line)
            index += 1
    if body:
        context = tuple(part for _, part in heading_path) or (title,)
        yield title, start_line, "\n".join(body), context


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


def _method_link_definitions(sections: Iterable[str]) -> dict[str, tuple[str, bool]]:
    definitions: dict[str, tuple[str, bool]] = {}
    for section in sections:
        for line in section.splitlines():
            definition = _reference_definition(line)
            if definition is not None:
                label, target, has_method_term = definition
                definitions[_reference_key(label)] = (target, has_method_term)
    return definitions


def _mask_inline_code_spans(text: str) -> str:
    runs: list[tuple[int, int, int, bool]] = []
    index = 0
    backslashes = 0
    while index < len(text):
        character = text[index]
        if character == "\\":
            backslashes += 1
            index += 1
            continue
        if character != "`":
            backslashes = 0
            index += 1
            continue
        end = index + 1
        while end < len(text) and text[end] == "`":
            end += 1
        runs.append((index, end, end - index, backslashes % 2 == 1))
        backslashes = 0
        index = end

    next_run_by_length: dict[int, int] = {}
    next_run: list[int] = [-1] * len(runs)
    for run_index in range(len(runs) - 1, -1, -1):
        length = runs[run_index][2]
        next_run[run_index] = next_run_by_length.get(length, -1)
        next_run_by_length[length] = run_index

    spans: list[tuple[int, int]] = []
    run_index = 0
    while run_index < len(runs):
        start, _, _, escaped = runs[run_index]
        closing_run = next_run[run_index]
        if escaped or closing_run < 0:
            run_index += 1
            continue
        spans.append((start, runs[closing_run][1]))
        run_index = closing_run + 1
    if not spans:
        return text

    characters = list(text)
    for start, end in spans:
        characters[start:end] = [
            " " if char not in "\r\n" else char for char in text[start:end]
        ]
    return "".join(characters)


def _has_method_link(text: str, definitions: Mapping[str, tuple[str, bool]]) -> bool:
    lines = text.splitlines()
    text = "\n".join(line for line in lines if _reference_definition(line) is None)
    text = _mask_inline_code_spans(text)
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
                if definition is not None and (
                    _METHOD_TERMS.search(pending_label[0]) or definition[1]
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
                    if definition is not None and (
                        _METHOD_TERMS.search(reference_primary)
                        or _METHOD_TERMS.search(label)
                        or definition[1]
                    ):
                        return True
                    reference_primary = None
                else:
                    pending_label = (label, index)
        elif label_start is None and character not in " \t\r\n":
            reference_primary = None
    if pending_label is not None:
        definition = definitions.get(_reference_key(pending_label[0]))
        if definition is not None and (
            _METHOD_TERMS.search(pending_label[0]) or definition[1]
        ):
            return True
    return False


def _analyze_heading(
    heading: str,
    definitions: Mapping[str, tuple[str, bool]],
) -> tuple[int, bool, bool]:
    return (
        _measurement_count(heading),
        _BENCHMARK_LANGUAGE.search(heading) is not None,
        _has_method_link(heading, definitions),
    )


def benchmark_doc_findings(
    root: Path, paths: Iterable[Path], policy: BenchmarkDocPolicy
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

        lines = text.splitlines()
        method_definitions = _method_link_definitions(
            body for _, _, body, _ in _sections(lines)
        )
        heading_titles = {
            heading
            for _, _, _, heading_context in _sections(lines)
            for heading in heading_context
        }
        heading_analysis = {
            heading: _analyze_heading(heading, method_definitions)
            for heading in heading_titles
        }
        for section, line, body, heading_context in _sections(lines):
            if (relative_name, section) in exceptions:
                continue
            context_analysis = [
                heading_analysis[heading] for heading in heading_context
            ]
            measurements = _measurement_count(body) + sum(
                item[0] for item in context_analysis
            )
            if (
                measurements < policy.min_measurements
                or not _BENCHMARK_LANGUAGE.search(body)
                and not any(item[1] for item in context_analysis)
                or _has_method_link(body, method_definitions)
                or any(item[2] for item in context_analysis)
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
    root: Path, paths: Sequence[Path], policy: BenchmarkDocPolicy
) -> list[Finding]:
    """Adapt the benchmark documentation scanner to the built-in runner contract."""
    return benchmark_doc_findings(root, paths, policy)


def run_benchmark_docs_rule(
    root: Path, paths: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Resolve strict feature policy before invoking the prose analyzer."""
    return run_benchmark_docs_feature(
        root, paths, resolve_benchmark_docs_policy(config)
    )


def resolve_benchmark_docs_policy(config: QualityGateConfig) -> BenchmarkDocPolicy:
    """Resolve the strict benchmark-prose policy from validated config."""
    return require_policy(config.checks.benchmark_docs, "benchmark_docs")


def run_benchmark_docs_feature(
    root: Path, paths: Sequence[Path], policy: BenchmarkDocPolicy
) -> list[Finding]:
    """Run bounded benchmark prose review with its feature-owned policy type."""
    return check_benchmark_docs(root, paths, policy)


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_benchmark_docs_feature,
    policy_resolver=resolve_benchmark_docs_policy,
)
