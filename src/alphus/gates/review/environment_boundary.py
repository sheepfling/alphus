"""Bounded, nonexecuting review of declared Python environment boundaries.

Only a closed, straight-line grammar is assessed. A single unsupported statement
invalidates the function's analysis rather than preserving potentially stale facts.
Values and argv are compared in memory but never included in diagnostics.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope, rule_tag
from alphus.gates.review._module_bindings import module_binding_counts
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.environment_boundary import (
    EnvironmentBoundaryContract,
    EnvironmentBoundaryPolicy,
    EnvironmentChildContract,
)
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="environment-boundary",
    policy_field="environment_boundary",
    policy_model=EnvironmentBoundaryPolicy,
    output_shape="findings",
    summary=(
        "Reviews declared Python setting sources and literal child launches "
        "against propagation contracts."
    ),
    applies_to=("python",),
    domains=(),
    requires_files=False,
    display_name="Environment boundary review",
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="environment-boundary",
    finding_ids=(
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "environment-setting-propagation",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.CORRECTNESS,
            "environment-boundary-status",
        ),
    ),
    concern="declared-environment-propagation",
    claim_kind=ClaimKind.RISK,
    claim=(
        "A declared setting reaches a disallowed child under a bounded "
        "straight-line model; dynamic behavior remains unassessed."
    ),
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("declared-python-functions", "literal-child-launches"),
    languages_formats=("python",),
    evidence_kinds=(
        "declared-propagation-contract",
        "source-location",
        "coverage-status",
    ),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)

_PROPAGATION = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.CORRECTNESS,
    "environment-setting-propagation",
)
_STATUS = rule_tag(
    Scope.PYTHON, Framework.NONE, Category.CORRECTNESS, "environment-boundary-status"
)
_LAUNCHERS = frozenset({"run", "call", "check_call", "check_output"})
_LAUNCH_OPTIONS = frozenset(
    {"check", "capture_output", "text", "encoding", "errors", "timeout", "cwd", "shell"}
)


class _Presence(StrEnum):
    UNKNOWN = "unknown"
    PRESENT = "present"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class _Setting:
    """Track presence and source line only, never the actual setting value."""

    presence: _Presence = _Presence.UNKNOWN
    source_line: int | None = None


@dataclass(frozen=True, slots=True)
class _Launch:
    child: EnvironmentChildContract
    line: int
    setting: _Setting


class _Unsupported(ValueError):
    """A fixed, value-free reason that a function cannot be assessed."""


def _is_environment(node: ast.AST) -> bool:
    match node:
        case ast.Attribute(value=ast.Name(id="os"), attr="environ"):
            return True
        case _:
            return False


def _is_copy(node: ast.AST) -> bool:
    match node:
        case ast.Call(
            func=ast.Attribute(value=value, attr="copy"), args=[], keywords=[]
        ):
            return _is_environment(value)
        case _:
            return False


def _literal_argv(node: ast.expr) -> tuple[str, ...] | None:
    match node:
        case ast.List(elts=items) | ast.Tuple(elts=items):
            values: list[str] = []
            for item in items:
                match item:
                    case ast.Constant(value=str() as value):
                        values.append(value)
                    case _:
                        return None
            return tuple(values) if values else None
        case _:
            return None


def _has_annotation(node: ast.AST) -> bool:
    match node:
        case ast.arg(annotation=annotation):
            return annotation is not None
        case _:
            return False


def _supported_option(method: str, keyword: ast.keyword) -> bool:
    """Reject incompatible launcher options and obviously invalid literal values."""
    name = keyword.arg
    if name not in _LAUNCH_OPTIONS:
        return False
    if name in {"check", "capture_output"} and method != "run":
        return False
    match keyword.value:
        case ast.Constant(value=False) if name == "shell":
            return True
        case ast.Constant(value=bool()) if name in {"check", "capture_output", "text"}:
            return True
        case ast.Constant(value=str() as value) if name == "cwd":
            return "\x00" not in value
        case ast.Constant(value="utf-8") if name == "encoding":
            return True
        case ast.Constant(value=str() as value) if name == "errors":
            return value in {"strict", "replace", "ignore"}
        case ast.Constant(value=bool()):
            return False
        case ast.Constant(value=int() as value) if name == "timeout":
            return value >= 0
        case ast.Constant(value=float() as value) if name == "timeout":
            return math.isfinite(value) and value >= 0
        case ast.Constant(value=None) if name in {
            "timeout",
            "cwd",
            "encoding",
            "errors",
        }:
            return True
        case _:
            return False


def _function(
    tree: ast.Module, contract: EnvironmentBoundaryContract
) -> ast.FunctionDef:
    """Require unambiguous standard imports and a plain top-level function."""
    for statement in tree.body:
        match statement:
            case ast.Import(names=names) if all(
                alias.name in {"os", "subprocess"} and alias.asname is None
                for alias in names
            ):
                pass
            case ast.FunctionDef() as function:
                if (
                    function.decorator_list
                    or function.args.defaults
                    or any(value is not None for value in function.args.kw_defaults)
                    or function.returns is not None
                    or any(_has_annotation(item) for item in ast.walk(function.args))
                ):
                    raise _Unsupported("definition-time expressions are unassessed")
            case ast.Expr(value=ast.Constant(value=str())) | ast.Pass():
                pass
            case _:
                raise _Unsupported(
                    "module execution or nonstandard imports are unassessed"
                )
    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.asname is None
    }
    if not {"os", "subprocess"} <= imports:
        raise _Unsupported("requires direct standard-library os and subprocess imports")
    counts = module_binding_counts(tree, ("os", "subprocess", contract.function))
    if any(counts.get(name) != 1 for name in ("os", "subprocess", contract.function)):
        raise _Unsupported("module bindings are ambiguous or rebound")
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == contract.function:
            if (
                node.decorator_list
                or node.args.defaults
                or any(value is not None for value in node.args.kw_defaults)
            ):
                raise _Unsupported(
                    "decorators and default argument expressions are unassessed"
                )
            for item in ast.walk(node):
                if isinstance(item, ast.arg) and item.arg in {"os", "subprocess"}:
                    raise _Unsupported("standard-library names are shadowed")
            return node
    raise _Unsupported("declared top-level function was not found")


class _Analysis:
    """Interpret only syntactic presence transitions, without executing source."""

    def __init__(self, contract: EnvironmentBoundaryContract) -> None:
        self.contract = contract
        self.ambient = _Setting()
        self.environments: dict[str, _Setting] = {}
        self.launches: list[_Launch] = []

    def environment(self, node: ast.expr) -> _Setting:
        if _is_environment(node) or _is_copy(node):
            return self.ambient
        match node:
            case ast.Constant(value=None):
                return self.ambient
            case ast.Name(id=name) if name in self.environments:
                return self.environments[name]
            case _:
                raise _Unsupported("dynamic or unsupported child environment")

    def require_mapping(self, target: ast.expr) -> None:
        if _is_environment(target):
            return
        match target:
            case ast.Name(id=name) if name in self.environments:
                return
            case _:
                raise _Unsupported("unknown environment mutation receiver")

    def write(self, target: ast.expr, state: _Setting) -> None:
        if _is_environment(target):
            self.ambient = state
        elif isinstance(target, ast.Name) and target.id in self.environments:
            self.environments[target.id] = state
        else:
            raise _Unsupported("unknown environment target or alias")

    def require_portable_key(self, key: str) -> None:
        if (
            key != self.contract.setting
            and key.casefold() == self.contract.setting.casefold()
        ):
            raise _Unsupported(
                "case-variant environment keys require platform-specific semantics"
            )

    def mutation(self, target: ast.expr, value: ast.expr | None, line: int) -> None:
        match target:
            case ast.Subscript(value=mapping, slice=ast.Constant(value=str() as key)):
                # Validate the receiver even for unrelated keys.
                if not key or "=" in key or "\x00" in key:
                    raise _Unsupported("invalid literal environment key")
                self.require_mapping(mapping)
                self.require_portable_key(key)
                match value:
                    case None:
                        pass
                    case ast.Constant(value=str() as text) if "\x00" not in text:
                        pass
                    case _:
                        raise _Unsupported(
                            "setting sources must be direct literal string writes"
                        )
                if key == self.contract.setting:
                    self.write(
                        mapping,
                        _Setting(
                            _Presence.ABSENT if value is None else _Presence.PRESENT,
                            line,
                        ),
                    )
            case _:
                raise _Unsupported("dynamic environment key or assignment")

    def launch(self, call: ast.Call, method: str) -> None:
        if len(call.args) != 1:
            raise _Unsupported("child argv must be one literal sequence")
        argv = _literal_argv(call.args[0])
        child = next(
            (child for child in self.contract.children if child.argv == argv), None
        )
        if child is None:
            raise _Unsupported(
                "child command is dynamic or not declared by this contract"
            )
        state = self.ambient
        seen: set[str] = set()
        for keyword in call.keywords:
            if keyword.arg is None or keyword.arg in seen:
                raise _Unsupported("expanded or duplicate launch keywords")
            seen.add(keyword.arg)
            if keyword.arg == "env":
                state = self.environment(keyword.value)
            elif not _supported_option(method, keyword):
                raise _Unsupported("unsupported launch option or expression")
        self.launches.append(_Launch(child, call.lineno, state))

    def statement(self, node: ast.stmt) -> None:
        match node:
            case ast.Pass() | ast.Expr(value=ast.Constant(value=str())):
                return
            case ast.Assign(targets=[ast.Name(id=name)], value=value) if _is_copy(
                value
            ):
                if name in {"os", "subprocess"}:
                    raise _Unsupported("standard-library names are rebound")
                self.environments[name] = self.ambient
            case ast.Assign(targets=[target], value=value):
                self.mutation(target, value, node.lineno)
            case ast.Delete(targets=[target]):
                self.mutation(target, None, node.lineno)
            case ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(value=ast.Name(id="subprocess"), attr=method)
                ) as call
            ) if method in _LAUNCHERS:
                self.launch(call, method)
            case ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(value=mapping, attr="pop"),
                    args=[ast.Constant(value=str() as key), ast.Constant(value=None)],
                    keywords=[],
                )
            ):
                self.require_mapping(mapping)
                self.require_portable_key(key)
                if key == self.contract.setting:
                    self.write(mapping, _Setting(_Presence.ABSENT, node.lineno))
            case _:
                raise _Unsupported(
                    "control flow, helpers, aliases or other statements are unassessed"
                )


def _status(contract: EnvironmentBoundaryContract, status: str, detail: str) -> Finding:
    return Finding(
        rule_id=_STATUS,
        path=contract.source_path,
        severity="info",
        message=f"contract {contract.name}: {status}; {detail}",
    )


def _inspect(
    source: str,
    contract: EnvironmentBoundaryContract,
    policy: EnvironmentBoundaryPolicy,
) -> list[Finding]:
    try:
        tree = ast.parse(source)
        function = _function(tree, contract)
        analysis = _Analysis(contract)
        for statement in function.body:
            analysis.statement(statement)
    except _Unsupported as error:
        return [_status(contract, "unassessed", str(error))]
    except (SyntaxError, ValueError, RecursionError):
        return [_status(contract, "unassessed", "source could not be parsed")]
    findings: list[Finding] = []
    assessed = 0
    unknown = 0
    observed: set[str] = set()
    for launch in analysis.launches:
        observed.add(launch.child.name)
        if launch.setting.presence is _Presence.UNKNOWN:
            unknown += 1
            continue
        assessed += 1
        if launch.child.allow_setting or launch.setting.presence is _Presence.ABSENT:
            continue
        findings.append(
            Finding(
                rule_id=_PROPAGATION,
                path=contract.source_path,
                line=launch.line,
                severity=policy.severity,
                message=(
                    f"contract {contract.name}: setting {contract.setting} "
                    f"from source line {launch.setting.source_line} reaches "
                    f"child {launch.child.name} at launch line {launch.line}, "
                    "whose contract sets allow_setting=false. "
                    "Use a command-local option or a deliberate per-child environment "
                    "copied from the ordinary environment; remove only this setting "
                    "for excluded children. Uncertain: static evidence is conditional "
                    "on this straight-line code executing with standard-library bindings; "
                    "external runtime changes are unassessed. "
                    "No values or argv recorded; no automatic edits."
                ),
            )
        )
    missing = len(contract.children) - len(observed)
    status = (
        "inspected"
        if assessed and not unknown and not missing
        else "partially-assessed"
        if assessed
        else "unassessed"
    )
    if status == "inspected" and not findings:
        status = "inspected-zero"
    findings.append(
        _status(
            contract,
            status,
            f"{assessed} assessed launches, {len(findings)} propagation candidates, "
            f"{unknown} launches with unknown sources, "
            f"{missing} declared children not observed; not a runtime safety proof",
        )
    )
    return findings


def check_environment_boundary(
    root: Path, paths: Iterable[Path], policy: EnvironmentBoundaryPolicy
) -> list[Finding]:
    """Report per-contract coverage separately from possible propagation defects."""
    checkout = root.resolve(strict=True)
    selected = {path.as_posix() for path in paths}
    findings: list[Finding] = []
    for contract in policy.contracts:
        if not policy.enabled:
            findings.append(
                _status(contract, "disabled", "policy enabled=false; source not read")
            )
            continue
        if any(
            matches_path(contract.source_path, pattern) for pattern in policy.exclude
        ):
            findings.append(
                _status(
                    contract,
                    "excluded",
                    "source excluded by review policy; source not read",
                )
            )
            continue
        if contract.source_path not in selected:
            findings.append(
                _status(
                    contract,
                    "not-selected",
                    "source absent from selected file inventory; source not read",
                )
            )
            continue
        path = checkout / contract.source_path
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(checkout)
        ):
            findings.append(
                _status(
                    contract,
                    "unassessed",
                    "source unavailable or outside the regular-file boundary",
                )
            )
            continue
        try:
            source = read_python_source(path)
        except (OSError, UnicodeError, SyntaxError):
            findings.append(
                _status(contract, "unassessed", "source could not be decoded or read")
            )
            continue
        findings.extend(_inspect(source, contract, policy))
    return findings


def resolve_environment_boundary_policy(
    config: QualityGateConfig,
) -> EnvironmentBoundaryPolicy:
    """Resolve the opt-in propagation contract from validated configuration."""
    return require_policy(config.checks.environment_boundary, "environment_boundary")


def run_environment_boundary_feature(
    root: Path, paths: Sequence[Path], policy: EnvironmentBoundaryPolicy
) -> list[Finding]:
    """Review selected source without executing it or changing the environment."""
    return check_environment_boundary(root, paths, policy)


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_environment_boundary_feature,
    policy_resolver=resolve_environment_boundary_policy,
)
