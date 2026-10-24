"""Plan opt-in native function-shape rules without measuring source ourselves."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeAlias, cast

from alphus.policy.sources import (
    FunctionShapeMetric,
    FunctionShapeOverride,
    FunctionShapePolicy,
    FunctionShapeTarget,
)

JsonScalar: TypeAlias = str | int | float | bool | None
FrozenJson: TypeAlias = (
    JsonScalar | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]
)


@dataclass(frozen=True, slots=True)
class FunctionShapeMetricPlan:
    metric: str
    native_rule: str
    definition: str
    maximum: int
    native_options: FrozenJson
    severity: str
    severity_mapping: str


@dataclass(frozen=True, slots=True)
class FunctionShapeOverridePlan:
    scope: Mapping[str, FrozenJson]
    metrics_replace_target: bool
    metrics: tuple[FunctionShapeMetricPlan, ...]
    severity: str


@dataclass(frozen=True, slots=True)
class FunctionShapeTargetPlan:
    language: str
    backend: str
    minimum_version: str
    scope: Mapping[str, FrozenJson]
    metrics: tuple[FunctionShapeMetricPlan, ...]
    overrides: tuple[FunctionShapeOverridePlan, ...]
    advisory_rollout: bool
    preview_requirements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FunctionShapePlan:
    """An immutable native plan with an explicit JSON serialization boundary."""

    schema_version: int
    policy: str
    targets: tuple[FunctionShapeTargetPlan, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize this immutable plan into fresh mutable JSON-compatible data."""
        return {
            "schema_version": self.schema_version,
            "policy": self.policy,
            "targets": [_target_dict(target) for target in self.targets],
        }


def _freeze_json(value: object) -> FrozenJson:
    """Recursively freeze JSON-compatible planner data for safe sharing."""
    if isinstance(value, Mapping):
        entries = cast(Mapping[object, object], value)
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in entries.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in cast(Sequence[object], value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"plan values must be JSON-compatible, got {type(value).__name__}")


def _thaw_json(value: FrozenJson) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _metric_dict(metric: FunctionShapeMetricPlan) -> dict[str, Any]:
    return {
        "metric": metric.metric,
        "native_rule": metric.native_rule,
        "definition": metric.definition,
        "maximum": metric.maximum,
        "native_options": _thaw_json(metric.native_options),
        "severity": metric.severity,
        "severity_mapping": metric.severity_mapping,
    }


def _override_dict(override: FunctionShapeOverridePlan) -> dict[str, Any]:
    return {
        "scope": _thaw_json(override.scope),
        "metrics_replace_target": override.metrics_replace_target,
        "metrics": [_metric_dict(metric) for metric in override.metrics],
        "severity": override.severity,
    }


def _target_dict(target: FunctionShapeTargetPlan) -> dict[str, Any]:
    return {
        "language": target.language,
        "backend": target.backend,
        "minimum_version": target.minimum_version,
        "scope": _thaw_json(target.scope),
        "metrics": [_metric_dict(metric) for metric in target.metrics],
        "overrides": [_override_dict(item) for item in target.overrides],
        "advisory_rollout": target.advisory_rollout,
        "preview_requirements": list(target.preview_requirements),
    }


def _valid_compilation_entries(value: object) -> bool:
    """Validate compile commands structurally and tolerate mapping-like records."""
    entries = cast(Sequence[Mapping[str, object]], value)
    try:
        if not entries:
            return False
        for entry in entries:
            if not _has_text(entry["directory"]) or not _has_text(entry["file"]):
                return False
            command = entry.get("command")
            if command is not None:
                if _has_text(command):
                    continue
                return False
            arguments = entry.get("arguments")
            if not arguments or any(
                not _has_text(argument)
                for argument in cast(Iterable[object], arguments)
            ):
                return False
    except (AttributeError, KeyError, TypeError):
        return False
    return True


def _has_text(value: object) -> bool:
    """Check text-like values by behavior instead of concrete runtime type."""
    strip = getattr(value, "strip", None)
    return callable(strip) and bool(strip())


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
        overrides = tuple(_override_plan(target, item) for item in target.overrides)
        targets.append(
            FunctionShapeTargetPlan(
                language=target.language,
                backend=target.backend,
                minimum_version=target.minimum_version,
                scope=cast(Mapping[str, FrozenJson], _freeze_json(scope)),
                metrics=metrics,
                overrides=overrides,
                advisory_rollout=True,
                preview_requirements=(
                    ("Ruff PLR1702 requires preview mode.",)
                    if target.backend == "ruff"
                    and any(m.name == "nesting" for m in target.metrics)
                    else ()
                ),
            )
        )
    return FunctionShapePlan(
        schema_version=1,
        policy="function-shape",
        targets=tuple(targets),
    )


def _metric_plans(
    target: FunctionShapeTarget,
    metrics: tuple[FunctionShapeMetric, ...],
    severity: str,
) -> tuple[FunctionShapeMetricPlan, ...]:
    result: list[FunctionShapeMetricPlan] = []
    for metric in metrics:
        native_rule, _, definition = _DEFINITIONS[target.backend][metric.name]
        result.append(
            FunctionShapeMetricPlan(
                metric=metric.name,
                native_rule=native_rule,
                definition=definition,
                maximum=metric.maximum,
                native_options=_freeze_json(_native_option(target, metric)),
                severity=severity,
                severity_mapping=(
                    "native rule severity is retained; use the native command's advisory exit behavior"
                    if target.backend == "ruff"
                    else "severity is represented by the native rule configuration"
                    if target.backend == "eslint"
                    else "native diagnostic severity and command exit behavior remain backend-owned"
                ),
            )
        )
    return tuple(result)


def _override_plan(
    target: FunctionShapeTarget, override: FunctionShapeOverride
) -> FunctionShapeOverridePlan:
    return FunctionShapeOverridePlan(
        scope=cast(
            Mapping[str, FrozenJson],
            _freeze_json({"include": override.include, "exclude": override.exclude}),
        ),
        metrics_replace_target=override.metrics is not None,
        metrics=_metric_plans(
            target,
            override.metrics or target.metrics,
            override.severity or target.severity,
        ),
        severity=override.severity or target.severity,
    )
