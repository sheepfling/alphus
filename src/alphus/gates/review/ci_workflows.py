"""Read-only review candidates for repeated GitHub Actions run blocks."""

from __future__ import annotations

import re
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
    match node:
        case MappingNode(value=entries):
            pass
        case _:
            return None
    result: dict[str, Node] = {}
    for key, value in entries:
        match key:
            case ScalarNode(value=key_value) if key_value not in result:
                result[key_value] = value
            case _:
                return None
    return result


def _is_alias_event(event: object) -> bool:
    match event:
        case AliasEvent():
            return True
        case _:
            return False


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


def _static_fingerprint(node: Node | None) -> _Fingerprint | None:
    """Canonicalize a static scalar/sequence/map without evaluating YAML."""
    match node:
        case ScalarNode(tag="tag:yaml.org,2002:str", value=value):
            if "${{" in value:
                return None
            return value
        case SequenceNode(tag="tag:yaml.org,2002:seq", value=items):
            fingerprints = tuple(_static_fingerprint(item) for item in items)
            return None if any(item is None for item in fingerprints) else fingerprints
        case MappingNode(tag="tag:yaml.org,2002:map", value=entries):
            values: dict[str, _Fingerprint] = {}
            for key, value in entries:
                match key:
                    case ScalarNode(value=key_text) if key_text not in values:
                        pass
                    case _:
                        return None
                fingerprint = _static_fingerprint(value)
                if fingerprint is None:
                    return None
                values[key_text] = fingerprint
            return tuple(sorted(values.items()))
        case _:
            return None


def _setup_action_blocks(
    source: str, path: str
) -> list[tuple[str, str, str, _Fingerprint, int]]:
    """Return exact static setup-action steps in simple, non-matrix jobs."""
    yaml_api = cast(_YamlApi, yaml)
    try:
        events = tuple(yaml_api.parse(source, Loader=yaml.BaseLoader))
        root = yaml_api.compose(source, Loader=yaml.BaseLoader)
    except yaml.YAMLError as error:
        raise ValueError(
            f"cannot parse GitHub Actions workflow {path}: {error}"
        ) from error
    if any(_is_alias_event(event) for event in events):
        return []
    workflow = _mapping(root)
    jobs = _mapping(workflow.get("jobs") if workflow is not None else None)
    if jobs is None:
        return []

    records: list[tuple[str, str, str, _Fingerprint, int]] = []
    for job_name, job_node in jobs.items():
        job = _mapping(job_node)
        if (
            job is None
            or not set(job) <= {"name", "runs-on", "steps"}
            or "runs-on" not in job
        ):
            # Conditions, matrices and other job context are not compared.
            continue
        runner = _fingerprint(job["runs-on"])
        if runner is None:
            continue
        steps = job.get("steps")
        match steps:
            case SequenceNode(value=step_nodes):
                pass
            case _:
                continue
        for step_node in step_nodes:
            step = _mapping(step_node)
            if step is None or not set(step) <= {"name", "uses", "with"}:
                # Conditional or otherwise contextual setup is intentionally skipped.
                continue
            action_node = step.get("uses")
            match action_node:
                case ScalarNode(value=action, start_mark=mark) if (
                    "${{" not in action
                    and "@" in action
                    and re.fullmatch(r"[^/\s]+/(?:.*/)?setup-[^@/\s]+@[^$\s]+", action)
                    is not None
                ):
                    pass
                case _:
                    continue
            settings = _static_fingerprint(step.get("with"))
            if "with" in step and settings is None:
                continue
            records.append(
                (repr(runner), job_name, action, settings or (), mark.line + 1)
            )
    return records


def _literal_matrix_values(node: Node) -> bool:
    match node:
        case SequenceNode(value=items) if items:
            for item in items:
                match item:
                    case ScalarNode(value=value) if "${{" not in value:
                        continue
                    case _:
                        return False
            return True
        case _:
            return False


def _run_blocks(
    source: str,
    path: str,
    minimum_run_lines: int,
    matrix_allowlist: tuple[str, ...] = (),
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
    if any(_is_alias_event(event) for event in events):
        return []
    workflow = _mapping(root)
    jobs = _mapping(workflow.get("jobs") if workflow is not None else None)
    if jobs is None:
        return []

    records: list[tuple[str, str, str, int]] = []
    for job_name, job_node in jobs.items():
        job = _mapping(job_node)
        if job is None or not set(job) <= {"name", "runs-on", "steps", "strategy"}:
            # This excludes matrices, job conditions, permissions, environments,
            # services, dependencies and other job-specific execution context.
            continue
        runner = _fingerprint(job.get("runs-on")) if "runs-on" in job else None
        strategy = _mapping(job.get("strategy")) if "strategy" in job else None
        matrix = _mapping(strategy.get("matrix")) if strategy is not None else None
        matrix_safe = (
            strategy is not None
            and set(strategy) == {"matrix"}
            and matrix is not None
            and bool(matrix)
            and all(_literal_matrix_values(value) for value in matrix.values())
        )
        steps = job.get("steps")
        if runner is None:
            continue
        match steps:
            case SequenceNode(value=step_nodes):
                pass
            case _:
                continue
        for step_node in step_nodes:
            step = _mapping(step_node)
            if step is None or not set(step) <= {"name", "run"}:
                # `if`, env, shell, working-directory, uses and similar context
                # make this initial exact-block comparison uncertain.
                continue
            run = step.get("run")
            match run:
                case ScalarNode(value=script, style=style, start_mark=mark) if (
                    style in {"|", ">"}
                    and len(script.splitlines()) >= minimum_run_lines
                    and "${{" not in script
                    and (
                        "strategy" not in job
                        or (matrix_safe and script in matrix_allowlist)
                    )
                ):
                    records.append((repr(runner), job_name, script, mark.line + 1))
                case _:
                    continue
    return records


def _azure_blocks(
    source: str, path: str, minimum: int
) -> list[tuple[str, str, str, int]]:
    """Return exact static Azure job script candidates; contextual jobs abstain."""
    yaml_api = cast(_YamlApi, yaml)
    try:
        events = tuple(yaml_api.parse(source, Loader=yaml.BaseLoader))
        root = yaml_api.compose(source, Loader=yaml.BaseLoader)
    except yaml.YAMLError as error:
        raise ValueError(
            f"cannot parse Azure Pipelines workflow {path}: {error}"
        ) from error
    if any(_is_alias_event(event) for event in events):
        return []
    pipeline = _mapping(root)
    jobs_node = pipeline.get("jobs") if pipeline is not None else None
    match jobs_node:
        case SequenceNode(value=job_nodes):
            pass
        case _:
            return []
    records: list[tuple[str, str, str, int]] = []
    for entry in job_nodes:
        job = _mapping(entry)
        if job is None or not set(job) <= {"job", "displayName", "pool", "steps"}:
            continue
        name_node, pool_node = job.get("job"), job.get("pool")
        match name_node:
            case ScalarNode(value=value):
                name = value
            case _:
                name = None
        pool = _fingerprint(pool_node)
        steps = job.get("steps")
        if name is None or pool is None:
            continue
        match steps:
            case SequenceNode(value=step_nodes):
                pass
            case _:
                continue
        for step_node in step_nodes:
            step = _mapping(step_node)
            if step is None or not set(step) <= {"displayName", "script", "bash"}:
                continue
            command = step.get("script", step.get("bash"))
            match command:
                case ScalarNode(value=script, style=style, start_mark=mark) if (
                    style in {"|", ">"}
                    and len(script.splitlines()) >= minimum
                    and "$ (" not in script
                    and "$(" not in script
                    and "${{" not in script
                ):
                    records.append((repr(pool), name, script, mark.line + 1))
                case _:
                    continue
    return records


def workflow_run_findings(
    source: str, path: str, policy: CiWorkflowPolicy
) -> list[Finding]:
    """Group identical static multiline run blocks across context-matched jobs."""
    azure = any(matches_path(path, pattern) for pattern in policy.azure_workflow_paths)
    blocks = (
        _azure_blocks(source, path, policy.minimum_run_lines)
        if azure
        else _run_blocks(
            source, path, policy.minimum_run_lines, policy.matrix_invariant_run_blocks
        )
    )
    groups: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for runner, job, script, line in blocks:
        if script in policy.ignore_run_blocks:
            continue
        groups[(runner, script)].append((job, line))

    findings: list[Finding] = []
    for (_, script), occurrences in sorted(groups.items(), key=lambda item: item[0]):
        unique_jobs = sorted({job for job, _ in occurrences})
        matrix_only = (
            len(unique_jobs) == 1 and script in policy.matrix_invariant_run_blocks
        )
        if len(unique_jobs) < 2 and not matrix_only:
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
                (
                    "allowlisted static repository check repeats in each matrix leg: "
                    if matrix_only
                    else "identical static multiline workflow command appears in distinct jobs: "
                )
                + f"{examples}; review whether a checked-in shared script would help. "
                "This is a duplication candidate, not proof the jobs are redundant. "
                "Matrix-dependent tests stay in their legs.",
                locations[0][0],
                policy.severity,
            )
        )
    if not azure:
        setup_groups: dict[tuple[str, str, _Fingerprint], list[tuple[str, int]]] = (
            defaultdict(list)
        )
        for runner, job, action, settings, line in _setup_action_blocks(source, path):
            if action in policy.ignore_setup_actions:
                continue
            setup_groups[(runner, action, settings)].append((job, line))
        for (_, action, _settings), occurrences in sorted(
            setup_groups.items(),
            key=lambda item: (item[0][0], item[0][1], repr(item[0][2])),
        ):
            jobs = sorted({job for job, _ in occurrences})
            if len(jobs) < 2:
                continue
            locations = sorted((line, job) for job, line in occurrences)
            examples = ", ".join(f"{job} (line {line})" for line, job in locations)
            findings.append(
                Finding(
                    rule_tag(
                        Scope.ANY,
                        Framework.NONE,
                        Category.ORCHESTRATION,
                        "repeated-workflow-setup-action",
                    ),
                    path,
                    (
                        f"identical static setup action {action!r} appears in distinct jobs: "
                        f"{examples}; review whether shared workflow configuration would help. "
                        "Jobs have isolated environments, so repeated setup may be required; "
                        "this is a duplication candidate, not a removal recommendation."
                    ),
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
            or not any(
                matches_path(name, pattern)
                for pattern in (*policy.workflow_paths, *policy.azure_workflow_paths)
            )
        ):
            continue
        path = checkout / relative
        if path.is_file():
            findings.extend(workflow_run_findings(read_utf8_text(path), name, policy))
    return findings
