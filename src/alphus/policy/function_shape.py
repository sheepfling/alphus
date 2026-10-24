"""Plan opt-in native function-shape rules without measuring source ourselves."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict, cast

from alphus.policy.sources import (
    FunctionShapeMetric,
    FunctionShapeOverride,
    FunctionShapePolicy,
    FunctionShapeTarget,
)


class FunctionShapeMetricPlan(TypedDict):
    metric: str
    native_rule: str
    definition: str
    maximum: int
    native_options: Mapping[str, object]
    severity: str
    severity_mapping: str


class FunctionShapeTargetPlan(TypedDict):
    language: str
    backend: str
    minimum_version: str
    scope: Mapping[str, object]
    metrics: list[FunctionShapeMetricPlan]
    overrides: list[FunctionShapeOverridePlan]
    advisory_rollout: bool
    preview_requirements: list[str]


class FunctionShapePlan(TypedDict):
    schema_version: int
    policy: str
    targets: list[FunctionShapeTargetPlan]


class FunctionShapeOverridePlan(TypedDict):
    scope: Mapping[str, object]
    metrics_replace_target: bool
    metrics: list[FunctionShapeMetricPlan]
    severity: str


def _valid_compilation_entries(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for entry in cast(list[object], value):
        if not isinstance(entry, dict):
            return False
        record = cast(Mapping[object, object], entry)
        if not isinstance(record.get("directory"), str) or not record["directory"]:
            return False
        if not isinstance(record.get("file"), str) or not record["file"]:
            return False
        command = record.get("command")
        arguments = record.get("arguments")
        if isinstance(command, str) and command:
            continue
        if (
            not isinstance(arguments, list)
            or not arguments
            or any(
                not isinstance(argument, str) or not argument
                for argument in cast(list[object], arguments)
            )
        ):
            return False
    return True


_DEFINITIONS: dict[str, dict[str, tuple[str, str, str]]] = {
    "ruff": {
        "parameters": (
            "PLR0913",
            "lint.pylint.max-args",
            "Ruff PLR0913 count: bound self/cls receivers and *args/**kwargs are excluded; defaulted and keyword-only parameters count. The positional-only metric is separate.",
        ),
        "nesting": (
            "PLR1702",
            "lint.pylint.max-nested-blocks",
            "Nested block count as implemented by Ruff PLR1702; preview rule and requires preview mode.",
        ),
        "statements": (
            "PLR0915",
            "lint.pylint.max-statements",
            "Statement count as implemented by Ruff PLR0915.",
        ),
    },
    "pylint": {
        "parameters": ("R0913", "design.max-args", "Pylint R0913 argument count."),
        "nesting": (
            "R1702",
            "design.max-nested-blocks",
            "Pylint R1702 nested-block count.",
        ),
        "statements": (
            "R0915",
            "design.max-statements",
            "Pylint R0915 statement count.",
        ),
    },
    "eslint": {
        "parameters": (
            "max-params",
            "max-params",
            "ESLint max-params counts declared parameters, including defaulted and rest parameters; a destructured parameter counts once. TypeScript this handling is controlled separately.",
        ),
        "nesting": (
            "max-depth",
            "max-depth",
            "ESLint max-depth counts nested blocks; callback nesting is a separate metric.",
        ),
        "statements": (
            "max-statements",
            "max-statements",
            "ESLint max-statements counts statements in a function body.",
        ),
    },
    "clang-tidy": {
        "parameters": (
            "readability-function-size",
            "ParameterThreshold",
            "clang-tidy readability-function-size parameter threshold; macros and template instantiation behavior follows the selected clang-tidy version.",
        ),
        "nesting": (
            "readability-function-size",
            "NestingThreshold",
            "clang-tidy readability-function-size nesting threshold; macro expansion can affect counts unless IgnoreMacros is enabled.",
        ),
        "statements": (
            "readability-function-size",
            "StatementThreshold",
            "clang-tidy readability-function-size statement threshold; CountMemberInitAsStmt is a separate native option.",
        ),
    },
}


def _native_option(
    target: FunctionShapeTarget, metric: FunctionShapeMetric
) -> dict[str, object]:
    native_rule, option, _ = _DEFINITIONS[target.backend][metric.name]
    if target.backend == "eslint":
        return {"rule": native_rule, "value": [target.severity, metric.maximum]}
    if target.backend == "clang-tidy":
        return {
            "Checks": f"{native_rule}",
            "CheckOptions": [
                {"key": f"{native_rule}.{option}", "value": str(metric.maximum)},
                {
                    "key": f"{native_rule}.IgnoreMacros",
                    "value": str(target.ignore_macros or False).lower(),
                },
                {
                    "key": f"{native_rule}.CountMemberInitAsStmt",
                    "value": str(
                        target.count_member_initializers_as_statements
                        if target.count_member_initializers_as_statements is not None
                        else True
                    ).lower(),
                },
            ],
        }
    if target.backend == "ruff":
        settings: dict[str, object] = {
            "lint.extend-select": [native_rule],
            option: metric.maximum,
        }
        if metric.name == "nesting":
            settings["preview"] = True
        return settings
    return {"enable": [native_rule], option: metric.maximum}


def plan_function_shape(policy: FunctionShapePolicy, root: Path) -> FunctionShapePlan:
    """Return a stable, read-only native configuration plan for each target."""
    checkout = root.resolve(strict=True)
    targets: list[FunctionShapeTargetPlan] = []
    for target in policy.targets:
        metrics = _metric_plans(target, target.metrics, target.severity)
        scope: dict[str, object] = {
            "include": target.include,
            "exclude": target.exclude,
        }
        if target.language == "cpp":
            if target.compilation_database is not None:
                database = (checkout / target.compilation_database).resolve()
                if not database.is_relative_to(checkout) or not database.is_file():
                    raise ValueError(
                        f"clang-tidy compilation database is missing or outside the checkout: {target.compilation_database}"
                    )
                try:
                    entries = json.loads(database.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as error:
                    raise ValueError(
                        f"clang-tidy compilation database is unreadable or invalid: {target.compilation_database}"
                    ) from error
                if not _valid_compilation_entries(entries):
                    raise ValueError(
                        f"clang-tidy compilation database has no valid command entries: {target.compilation_database}"
                    )
                scope["compilation_database"] = target.compilation_database
            scope["operational_requirement"] = (
                "Run clang-tidy with valid compilation context; missing or invalid context is an execution failure, not a clean result."
            )
        overrides = [_override_plan(target, item) for item in target.overrides]
        targets.append(
            {
                "language": target.language,
                "backend": target.backend,
                "minimum_version": target.minimum_version,
                "scope": scope,
                "metrics": metrics,
                "overrides": overrides,
                "advisory_rollout": True,
                "preview_requirements": (
                    ["Ruff PLR1702 requires preview mode."]
                    if target.backend == "ruff"
                    and any(m.name == "nesting" for m in target.metrics)
                    else []
                ),
            }
        )
    return {"schema_version": 1, "policy": "function-shape", "targets": targets}


def _metric_plans(
    target: FunctionShapeTarget,
    metrics: tuple[FunctionShapeMetric, ...],
    severity: str,
) -> list[FunctionShapeMetricPlan]:
    result: list[FunctionShapeMetricPlan] = []
    for metric in metrics:
        native_rule, _, definition = _DEFINITIONS[target.backend][metric.name]
        result.append(
            {
                "metric": metric.name,
                "native_rule": native_rule,
                "definition": definition,
                "maximum": metric.maximum,
                "native_options": _native_option(target, metric),
                "severity": severity,
                "severity_mapping": (
                    "native rule severity is retained; use the native command's advisory exit behavior"
                    if target.backend == "ruff"
                    else "severity is represented by the native rule configuration"
                    if target.backend == "eslint"
                    else "native diagnostic severity and command exit behavior remain backend-owned"
                ),
            }
        )
    return result


def _override_plan(
    target: FunctionShapeTarget, override: FunctionShapeOverride
) -> FunctionShapeOverridePlan:
    return {
        "scope": {"include": override.include, "exclude": override.exclude},
        "metrics_replace_target": override.metrics is not None,
        "metrics": _metric_plans(
            target,
            override.metrics or target.metrics,
            override.severity or target.severity,
        ),
        "severity": override.severity or target.severity,
    }
