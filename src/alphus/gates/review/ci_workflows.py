"""Read-only review candidates for repeated GitHub Actions run blocks."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, TypeAlias, cast

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from alphus.config import CiWorkflowPolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_utf8_text

_Fingerprint: TypeAlias = str | tuple[object, ...]


class _YamlApi(Protocol):
    """Narrow the PyYAML functions whose upstream stubs return Incomplete."""

    def parse(self, stream: str, Loader: type[yaml.BaseLoader]) -> Iterable[object]: ...

    def compose(self, stream: str, Loader: type[yaml.BaseLoader]) -> Node | None: ...


def _mapping(node: Node | None) -> dict[str, Node] | None:
    if not isinstance(node, MappingNode):
        return None
    result: dict[str, Node] = {}
    for key, value in node.value:
        if not isinstance(key, ScalarNode) or key.value in result:
            return None
        result[key.value] = value
    return result


def _fingerprint(node: Node | None) -> _Fingerprint | None:
    match node:
        case ScalarNode(value=value):
            if "${{" in value:
                return None
            return value
        case SequenceNode(value=items):
            fingerprints = tuple(_fingerprint(item) for item in items)
            return None if any(item is None for item in fingerprints) else fingerprints
        case _:
            return None


def _run_blocks(
    source: str, path: str, minimum_run_lines: int
) -> list[tuple[str, str, str, int]]:
    """Return eligible (runner, job, script, line) records from one workflow."""
    yaml_api = cast(_YamlApi, yaml)
    try:
        events = tuple(yaml_api.parse(source, Loader=yaml.BaseLoader))
        root = yaml_api.compose(source, Loader=yaml.BaseLoader)
    except yaml.YAMLError as error:
        raise ValueError(
            f"cannot parse GitHub Actions workflow {path}: {error}"
        ) from error
    # Anchors and aliases can share node identities and obscure which job owns a
    # run block. Abstain on the file rather than attributing a location wrongly.
    if any(isinstance(event, AliasEvent) for event in events):
        return []
    workflow = _mapping(root)
    jobs = _mapping(workflow.get("jobs") if workflow is not None else None)
    if jobs is None:
        return []

    records: list[tuple[str, str, str, int]] = []
    for job_name, job_node in jobs.items():
        job = _mapping(job_node)
        if job is None or not set(job) <= {"name", "runs-on", "steps"}:
            # This excludes matrices, job conditions, permissions, environments,
            # services, dependencies and other job-specific execution context.
            continue
        runner = _fingerprint(job.get("runs-on")) if "runs-on" in job else None
        steps = job.get("steps")
        if runner is None or not isinstance(steps, SequenceNode):
            continue
        for step_node in steps.value:
            step = _mapping(step_node)
            if step is None or not set(step) <= {"name", "run"}:
                # `if`, env, shell, working-directory, uses and similar context
                # make this initial exact-block comparison uncertain.
                continue
            run = step.get("run")
            if (
                not isinstance(run, ScalarNode)
                or run.style not in {"|", ">"}
                or len(run.value.splitlines()) < minimum_run_lines
                or "${{" in run.value
            ):
                continue
            records.append((repr(runner), job_name, run.value, run.start_mark.line + 1))
    return records


def workflow_run_findings(
    source: str, path: str, policy: CiWorkflowPolicy
) -> list[Finding]:
    """Group identical static multiline run blocks across context-matched jobs."""
    blocks = _run_blocks(source, path, policy.minimum_run_lines)
    groups: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for runner, job, script, line in blocks:
        if script in policy.ignore_run_blocks:
            continue
        groups[(runner, script)].append((job, line))

    findings: list[Finding] = []
    for (_, script), occurrences in sorted(groups.items(), key=lambda item: item[0]):
        unique_jobs = sorted({job for job, _ in occurrences})
        if len(unique_jobs) < 2:
            continue
        locations = sorted((line, job) for job, line in occurrences)
        examples = ", ".join(f"{job} (line {line})" for line, job in locations)
        findings.append(
            Finding(
                rule_tag(
                    Scope.ANY,
                    Framework.NONE,
                    Category.ORCHESTRATION,
                    "duplicate-workflow-run",
                ),
                path,
                "identical static multiline workflow command appears in distinct jobs: "
                f"{examples}; review whether a checked-in shared script would help. "
                "This is a duplication candidate, not proof the jobs are redundant.",
                locations[0][0],
                policy.severity,
            )
        )
    return findings


def check_ci_workflows(
    root: Path, paths: Iterable[Path], policy: CiWorkflowPolicy
) -> list[Finding]:
    """Inspect selected GitHub workflow YAML without executing or rewriting it."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if (
            relative.suffix.lower() not in policy.extensions
            or any(matches_path(name, pattern) for pattern in policy.exclude)
            or not any(matches_path(name, pattern) for pattern in policy.workflow_paths)
        ):
            continue
        path = checkout / relative
        if path.is_file():
            findings.extend(workflow_run_findings(read_utf8_text(path), name, policy))
    return findings
