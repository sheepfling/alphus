"""Read-only review candidates for repeated GitHub Actions run blocks."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final, Protocol, TypeAlias, cast

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.review import CiWorkflowPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_utf8_text

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="ci-workflows",
    policy_field="ci_workflows",
    policy_model=CiWorkflowPolicy,
    output_shape="findings",
    summary="Reviews selected CI workflow commands for repeated job work.",
    applies_to=("yaml", "ci"),
    domains=(),
    requires_files=False,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="ci-workflows",
    finding_ids=(
        RuleTag(
            Scope.ANY,
            Framework.NONE,
            Category.ORCHESTRATION,
            "duplicate-workflow-run",
        ),
        RuleTag(
            Scope.ANY,
            Framework.NONE,
            Category.ORCHESTRATION,
            "long-inline-workflow-script",
        ),
        RuleTag(
            Scope.ANY,
            Framework.NONE,
            Category.ORCHESTRATION,
            "repeated-workflow-setup-action",
        ),
    ),
    concern="repeated-ci-workflow-work",
    claim_kind=ClaimKind.RISK,
    claim=(
        "Static workflow repetition is a review candidate; isolated jobs, matrix "
        "differences, and runtime expressions can make repeated work necessary."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-yaml-workflows", "static-commands-and-setup"),
    languages_formats=("yaml", "github-actions", "azure-pipelines"),
    evidence_kinds=("workflow-policy", "static-yaml-nodes", "source-location"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)

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


def _contains_azure_expression(node: Node | None) -> bool:
    """Recognize Azure runtime expressions in any static task/pool value."""
    match node:
        case ScalarNode(value=value):
            return re.search(r"\$\(|\$\[|\$\{\{", value) is not None
        case SequenceNode(value=items):
            return any(_contains_azure_expression(item) for item in items)
        case MappingNode(value=entries):
            return any(
                _contains_azure_expression(key) or _contains_azure_expression(value)
                for key, value in entries
            )
        case _:
            return True


def _azure_fingerprint(node: Node | None) -> _Fingerprint | None:
    if _contains_azure_expression(node):
        return None
    return _static_fingerprint(node)


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


def _matrix_has_multiple_literal_legs(axes: Iterable[Node]) -> bool:
    """Return whether a supported literal matrix has more than one leg."""
    for axis in axes:
        match axis:
            case SequenceNode(value=values) if len(values) > 1:
                return True
            case _:
                continue
    return False


def _block_scalar_nonblank_lines(node: ScalarNode, source: str, script: str) -> int:
    """Count physical nonblank body lines, including folded YAML block scalars."""
    source_lines = source.splitlines()
    end_line = node.end_mark.line + int(node.end_mark.column > 0)
    body = source_lines[node.start_mark.line + 1 : end_line]
    if node.style in {"|", ">"} and body:
        return sum(bool(line.strip()) for line in body)
    return sum(bool(line.strip()) for line in script.splitlines())


def _run_blocks(
    source: str,
    path: str,
    minimum_run_lines: int,
    maximum_inline_run_lines: int,
    matrix_allowlist: tuple[str, ...] = (),
) -> list[tuple[str, str, str, int, bool, int]]:
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

    records: list[tuple[str, str, str, int, bool, int]] = []
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
            and _matrix_has_multiple_literal_legs(matrix.values())
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
                case (
                    ScalarNode(value=script, style=style, start_mark=mark) as scalar
                ) if (
                    style in {"|", ">"}
                    and (
                        len(script.splitlines()) >= minimum_run_lines
                        or _block_scalar_nonblank_lines(scalar, source, script)
                        >= maximum_inline_run_lines
                    )
                    and "${{" not in script
                    and (
                        "strategy" not in job
                        or (matrix_safe and script in matrix_allowlist)
                    )
                ):
                    records.append(
                        (
                            repr(runner),
                            job_name,
                            script,
                            mark.line + 1,
                            matrix_safe,
                            _block_scalar_nonblank_lines(scalar, source, script),
                        )
                    )
                case _:
                    continue
    return records


def _static_azure_matrix(strategy: Node | None) -> bool:
    """Recognize only a literal Azure matrix with at least two named legs."""
    strategy_mapping = _mapping(strategy)
    if strategy_mapping is None or set(strategy_mapping) != {"matrix"}:
        return False
    matrix = _mapping(strategy_mapping.get("matrix"))
    return bool(
        matrix
        and len(matrix) >= 2
        and all(_azure_fingerprint(leg) is not None for leg in matrix.values())
    )


def _azure_blocks(
    source: str,
    path: str,
    minimum: int,
    maximum_inline_run_lines: int,
    matrix_allowlist: tuple[str, ...] = (),
) -> list[tuple[str, str, str, int, bool, int]]:
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
    records: list[tuple[str, str, str, int, bool, int]] = []
    for entry in job_nodes:
        job = _mapping(entry)
        if job is None or not set(job) <= {
            "job",
            "displayName",
            "pool",
            "steps",
            "strategy",
        }:
            continue
        matrix_scoped = _static_azure_matrix(job.get("strategy"))
        if "strategy" in job and not matrix_scoped:
            continue
        name_node, pool_node = job.get("job"), job.get("pool")
        match name_node:
            case ScalarNode(value=value):
                name = value
            case _:
                name = None
        pool = _azure_fingerprint(pool_node)
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
                case (
                    ScalarNode(value=script, style=style, start_mark=mark) as scalar
                ) if (
                    style in {"|", ">"}
                    and (
                        len(script.splitlines()) >= minimum
                        or _block_scalar_nonblank_lines(scalar, source, script)
                        >= maximum_inline_run_lines
                    )
                    and "$ (" not in script
                    and "$(" not in script
                    and "${{" not in script
                    and not re.search(
                        r"(?:\$[A-Za-z_][A-Za-z0-9_]*|\$\{[^}]+\}|%[^%]+%|![^!]+!)",
                        script,
                    )
                    and (not matrix_scoped or script in matrix_allowlist)
                ):
                    records.append(
                        (
                            repr(pool),
                            name,
                            script,
                            mark.line + 1,
                            matrix_scoped,
                            _block_scalar_nonblank_lines(scalar, source, script),
                        )
                    )
                case _:
                    continue
    return records


_AZURE_SETUP_TASK = re.compile(
    r"(?:UsePythonVersion|UseDotNet|NodeTool|JavaToolInstaller|GoTool|UseRubyVersion)@\d+",
    re.IGNORECASE,
)


def _azure_setup_task_blocks(
    source: str, path: str
) -> list[tuple[str, str, str, _Fingerprint, int]]:
    """Return exact setup-task records from jobs with matching static pools."""
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
    records: list[tuple[str, str, str, _Fingerprint, int]] = []
    for entry in job_nodes:
        job = _mapping(entry)
        if job is None or not set(job) <= {"job", "displayName", "pool", "steps"}:
            continue
        pool = _azure_fingerprint(job.get("pool"))
        name_node = job.get("job")
        match name_node:
            case ScalarNode(value=name):
                pass
            case _:
                continue
        if pool is None:
            continue
        match job.get("steps"):
            case SequenceNode(value=step_nodes):
                pass
            case _:
                continue
        for step_node in step_nodes:
            step = _mapping(step_node)
            if step is None or not set(step) <= {"displayName", "task", "inputs"}:
                continue
            match step.get("task"):
                case ScalarNode(value=task, start_mark=mark) if (
                    _AZURE_SETUP_TASK.fullmatch(task)
                ):
                    pass
                case _:
                    continue
            inputs = _azure_fingerprint(step.get("inputs"))
            if "inputs" in step and inputs is None:
                continue
            records.append((repr(pool), name, task, inputs or (), mark.line + 1))
    return records


def workflow_run_findings(
    source: str, path: str, policy: CiWorkflowPolicy
) -> list[Finding]:
    """Group identical static multiline run blocks across context-matched jobs."""
    azure = any(matches_path(path, pattern) for pattern in policy.azure_workflow_paths)
    blocks = (
        _azure_blocks(
            source,
            path,
            policy.minimum_run_lines,
            policy.maximum_inline_run_lines,
            policy.matrix_invariant_run_blocks,
        )
        if azure
        else _run_blocks(
            source,
            path,
            policy.minimum_run_lines,
            policy.maximum_inline_run_lines,
            policy.matrix_invariant_run_blocks,
        )
    )
    findings: list[Finding] = []
    for _runner, job, script, line, _matrix_scoped, nonblank_lines in blocks:
        if (
            script in policy.ignore_run_blocks
            or nonblank_lines < policy.maximum_inline_run_lines
        ):
            continue
        findings.append(
            Finding(
                rule_tag(
                    Scope.ANY,
                    Framework.NONE,
                    Category.ORCHESTRATION,
                    "long-inline-workflow-script",
                ),
                path,
                (
                    f"static inline workflow script has {nonblank_lines} nonblank lines "
                    f"in job {job!r} (line {line}); review whether a checked-in script "
                    "would make this workflow easier to maintain. This is a maintainability "
                    "candidate, not evidence the steps or matrix are redundant."
                ),
                line,
                policy.severity,
            )
        )
    groups: dict[tuple[str, str], list[tuple[str, int, bool]]] = defaultdict(list)
    for runner, job, script, line, matrix_scoped, _nonblank_lines in blocks:
        if script in policy.ignore_run_blocks:
            continue
        if len(script.splitlines()) < policy.minimum_run_lines:
            continue
        groups[(runner, script)].append((job, line, matrix_scoped))

    for (_, script), occurrences in sorted(groups.items(), key=lambda item: item[0]):
        unique_jobs = sorted({job for job, _, _ in occurrences})
        matrix_only = len(unique_jobs) == 1 and all(
            matrix_scoped for _, _, matrix_scoped in occurrences
        )
        if len(unique_jobs) < 2 and not matrix_only:
            continue
        locations = sorted((line, job) for job, line, _ in occurrences)
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
    else:
        setup_groups: dict[tuple[str, str, _Fingerprint], list[tuple[str, int]]] = (
            defaultdict(list)
        )
        for pool, job, task, inputs, line in _azure_setup_task_blocks(source, path):
            setup_groups[(pool, task, inputs)].append((job, line))
        for (_, task, _inputs), occurrences in sorted(
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
                        f"identical static Azure setup task {task!r} appears in distinct jobs: "
                        f"{examples}; review whether a shared template would help. "
                        "Pool and task inputs match exactly, but this is a review candidate, "
                        "not a recommendation to remove setup from isolated jobs."
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


def run_ci_workflows_rule(
    root: Path, paths: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Adapt the read-only workflow reviewer to the typed built-in runner."""
    return check_ci_workflows(
        root,
        paths,
        require_policy(config.checks.ci_workflows, "ci_workflows"),
    )


ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_ci_workflows_rule,
)
