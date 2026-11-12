"""Generate an AST-derived audit inventory of built-in registrations."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.generate_morphology_manifest import (
    feature_registrations,
    typed_feature_output_shape,
)


@dataclass(frozen=True, slots=True)
class PolicyField:
    """One strict policy field referenced by a built-in check."""

    name: str
    annotation: str


@dataclass(frozen=True, slots=True)
class BuiltinCheck:
    """Current statically observed registration facts for one selector."""

    selector: str
    policy_field: str
    policy_inputs_observed: tuple[str, ...]
    policy_fields: tuple[PolicyField, ...]
    runner: str
    output_shape: str
    result_adapter: str
    requires_files: bool


@dataclass(frozen=True, slots=True)
class SelectionSurfaces:
    direct_cli: str
    profile: str


@dataclass(frozen=True, slots=True)
class ReportingSurfaces:
    direct_cli: str
    profile: str
    catalog: str


@dataclass(frozen=True, slots=True)
class BuiltinInventory:
    """Serialized audit contract; never consumed for runtime registration."""

    schema_version: int
    purpose: str
    policy_input_observation: str
    shared_selection_surfaces: SelectionSurfaces
    shared_reporting_surfaces: ReportingSurfaces
    selector_count_source: str
    selector_count: int
    checks: tuple[BuiltinCheck, ...]


@dataclass(frozen=True, slots=True)
class _CatalogRule:
    selector: str
    policy_field: str
    output_shape: str
    requires_files: bool


@dataclass(frozen=True, slots=True)
class _RunnerBinding:
    selector: str
    module: str
    name: str
    policy_inputs: tuple[str, ...]


def _literal_string(node: ast.expr | None, context: str) -> str:
    match node:
        case ast.Constant(value=str() as literal):
            return literal
        case _:
            raise ValueError(f"{context} must be a literal string")


def quality_rule_selectors(root: Path) -> tuple[str, ...]:
    """Read the current public selector Literal without importing its module."""
    generated_path = (
        root / "src" / "alphus" / "policy" / "_generated_quality_rule_names.py"
    )
    path = (
        generated_path
        if generated_path.is_file()
        else (root / "src" / "alphus" / "policy" / "base.py")
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        if (
            not isinstance(statement, ast.AnnAssign)
            or not isinstance(statement.target, ast.Name)
            or statement.target.id != "QualityRuleName"
        ):
            continue
        value: ast.expr | None = statement.value
        if (
            not isinstance(value, ast.Subscript)
            or not isinstance(value.value, ast.Name)
            or value.value.id != "Literal"
        ):
            raise ValueError(f"{path}: QualityRuleName must be a Literal")
        elements: tuple[ast.expr, ...]
        if isinstance(value.slice, ast.Tuple):
            elements = tuple(value.slice.elts)
        else:
            elements = (value.slice,)
        selectors = tuple(
            _literal_string(item, f"{path}: QualityRuleName") for item in elements
        )
        if len(selectors) != len(set(selectors)):
            raise ValueError(f"{path}: QualityRuleName contains duplicate selectors")
        return selectors
    raise ValueError(f"{path} does not define QualityRuleName")


def _catalog_rules(root: Path) -> tuple[_CatalogRule, ...]:
    """Read legacy literals and feature-owned catalog declarations statically."""
    path = root / "src" / "alphus" / "policy" / "catalog.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rules: list[_CatalogRule] = []
    for statement in tree.body:
        if (
            not isinstance(statement, ast.AnnAssign)
            or not isinstance(statement.target, ast.Name)
            or statement.target.id not in ("_LEGACY_RULE_SPECS", "RULE_SPECS")
        ):
            continue
        value: ast.expr | None = statement.value
        if not isinstance(value, ast.Call) or len(value.args) != 1:
            if statement.target.id == "RULE_SPECS":
                continue
            raise ValueError(f"{path}: legacy RuleSpecs must wrap a literal map")
        mapping: ast.expr = value.args[0]
        if not isinstance(mapping, ast.Dict):
            if statement.target.id == "RULE_SPECS":
                continue
            raise TypeError(f"{path}: legacy RuleSpecs must use a literal dict")
        for key, raw_spec in zip(mapping.keys, mapping.values, strict=True):
            selector = _literal_string(key, f"{path}: selector")
            match raw_spec:
                case ast.Call(
                    func=ast.Name(id="RuleSpec"),
                    args=[policy_field_node, shape_node, *_arguments],
                ):
                    pass
                case _:
                    raise ValueError(f"{path}: {selector} must use a RuleSpec literal")
            policy_field = _literal_string(
                policy_field_node, f"{path}: {selector} policy"
            )
            match shape_node:
                case ast.Attribute(attr=shape_name):
                    output_shape = shape_name.lower().replace("_", "-")
                case _:
                    raise TypeError(f"{path}: {selector} needs a literal output shape")
            requires_files = True
            for keyword in raw_spec.keywords:
                if keyword.arg == "requires_files":
                    match keyword.value:
                        case ast.Constant(value=bool() as literal_value):
                            requires_files = literal_value
                        case _:
                            raise ValueError(
                                f"{path}: {selector} requires_files must be literal"
                            )
            rules.append(
                _CatalogRule(
                    selector=selector,
                    policy_field=policy_field,
                    output_shape=output_shape,
                    requires_files=requires_files,
                )
            )
        if statement.target.id == "_LEGACY_RULE_SPECS":
            break
    rules.extend(
        _CatalogRule(
            selector=feature.selector,
            policy_field=feature.policy_field,
            output_shape=feature.output_shape,
            requires_files=feature.requires_files,
        )
        for feature in feature_registrations(root)
    )
    if not rules:
        raise ValueError(f"{path} has no legacy or feature-owned RuleSpecs")
    return tuple(rules)


def _check_policy_fields(root: Path) -> tuple[PolicyField, ...]:
    """Read the strict CheckPolicies field names and annotations statically."""
    path = root / "src" / "alphus" / "policy" / "orchestration.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        if not isinstance(statement, ast.ClassDef) or statement.name != "CheckPolicies":
            continue
        fields: list[PolicyField] = []
        for member in statement.body:
            if isinstance(member, ast.AnnAssign) and isinstance(
                member.target, ast.Name
            ):
                fields.append(
                    PolicyField(member.target.id, ast.unparse(member.annotation))
                )
        for feature in feature_registrations(root):
            class_name = feature.policy_model.rsplit(".", 1)[1]
            fields.append(PolicyField(feature.policy_field, f"{class_name} | None"))
        return tuple(fields)
    raise ValueError(f"{path} does not define CheckPolicies")


def _runner_policy_inputs(
    root: Path,
) -> tuple[_RunnerBinding, ...]:
    """Read literal theme bindings and direct policy references in their bodies."""
    runner_root = root / "src" / "alphus" / "gates"
    bindings: list[_RunnerBinding] = []
    for path in sorted(runner_root.glob("*/runners.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = {
            statement.name: statement
            for statement in tree.body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        module = f"alphus.gates.{path.parent.name}.runners"
        for statement in tree.body:
            if (
                not isinstance(statement, ast.AnnAssign)
                or not isinstance(statement.target, ast.Name)
                or not statement.target.id.endswith("_RULE_RUNNERS")
            ):
                continue
            value: ast.expr | None = statement.value
            if (
                not isinstance(value, ast.Call)
                or not isinstance(value.func, ast.Name)
                or value.func.id != "MappingProxyType"
                or len(value.args) != 1
            ):
                raise ValueError(f"{path}:{statement.target.id} must be a literal map")
            mapping: ast.expr = value.args[0]
            if not isinstance(mapping, ast.Dict):
                raise TypeError(f"{path}:{statement.target.id} must use a literal dict")
            for key, runner_expr in zip(mapping.keys, mapping.values, strict=True):
                selector = _literal_string(
                    key, f"{path}:{statement.target.id} selector"
                )
                scopes: list[ast.AST] = [runner_expr]
                runner_name = "<lambda>"
                match runner_expr:
                    case ast.Name(id=name):
                        runner_name = name
                        function = functions.get(runner_name)
                        if function is None:
                            raise ValueError(
                                f"{path}:{selector} references unknown local "
                                f"runner {runner_name!r}"
                            )
                        scopes.append(function)
                    case _:
                        pass
                policy_fields = {
                    node.attr
                    for scope in scopes
                    for node in ast.walk(scope)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Attribute)
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "config"
                    and node.value.attr == "checks"
                }
                bindings.append(
                    _RunnerBinding(
                        selector=selector,
                        module=module,
                        name=runner_name,
                        policy_inputs=tuple(sorted(policy_fields)),
                    )
                )
    for feature in feature_registrations(root):
        path = root.joinpath(
            "src", *feature.registration_module.split(".")
        ).with_suffix(".py")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        statements: tuple[ast.stmt, ...] = tuple(tree.body)
        registration: ast.expr | None = None
        for statement in statements:
            match statement:
                case ast.AnnAssign(
                    target=ast.Name(id="ALPHUS_FEATURE"),
                    value=ast.expr() as value,
                ):
                    registration = value
                    break
                case _:
                    pass
        match registration:
            case ast.Call(
                func=ast.Name(id=constructor_name)
                | ast.Attribute(attr=constructor_name),
                args=args,
                keywords=keywords,
            ):
                pass
            case _:
                raise ValueError(
                    f"{path}: ALPHUS_FEATURE must construct BuiltinFeature"
                )
        typed_shape = typed_feature_output_shape(constructor_name)
        if constructor_name != "BuiltinFeature" and typed_shape != feature.output_shape:
            raise ValueError(
                f"{path}: typed feature output shape does not match its declaration"
            )
        runner = (
            args[2]
            if len(args) > 2
            else next(
                (keyword.value for keyword in keywords if keyword.arg == "runner"),
                None,
            )
        )
        match runner:
            case ast.Name(id=runner_name):
                pass
            case _:
                raise TypeError(
                    f"{path}: ALPHUS_FEATURE runner must be a named function"
                )
        function = next(
            (
                statement
                for statement in tree.body
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                and statement.name == runner_name
            ),
            None,
        )
        if function is None:
            raise ValueError(f"{path}: unknown feature runner {runner_name!r}")
        policy_fields = {
            field_name
            for node in ast.walk(function)
            if (field_name := _config_policy_field(node)) is not None
        }
        bindings.append(
            _RunnerBinding(
                selector=feature.selector,
                module=feature.registration_module,
                name="ALPHUS_FEATURE",
                policy_inputs=tuple(sorted(policy_fields)),
            )
        )
    return tuple(bindings)


def _config_policy_field(node: ast.AST) -> str | None:
    match node:
        case ast.Attribute(
            attr=field_name,
            value=ast.Attribute(attr="checks", value=ast.Name(id="config")),
        ):
            return field_name
        case _:
            return None


def inventory(root: Path) -> BuiltinInventory:
    """Build a current-state registration audit from static source contracts."""
    selectors = quality_rule_selectors(root)
    catalog = _catalog_rules(root)
    policy_fields = _check_policy_fields(root)
    runner_bindings = _runner_policy_inputs(root)
    catalog_by_selector = {rule.selector: rule for rule in catalog}
    runner_by_selector = {binding.selector: binding for binding in runner_bindings}
    if len(catalog_by_selector) != len(catalog):
        raise ValueError("duplicate selector in the built-in RuleSpec catalog")
    if len(runner_by_selector) != len(runner_bindings):
        raise ValueError("duplicate selector in built-in theme runner bindings")
    if set(selectors) != set(catalog_by_selector) or set(selectors) != set(
        runner_by_selector
    ):
        raise ValueError("selector, RuleSpec, and runner declarations differ")
    field_types = {field.name: field.annotation for field in policy_fields}
    checks: list[BuiltinCheck] = []
    for selector in sorted(selectors):
        spec = catalog_by_selector[selector]
        binding = runner_by_selector[selector]
        observed_fields = tuple(sorted({spec.policy_field, *binding.policy_inputs}))
        missing_fields = set(observed_fields) - set(field_types)
        if missing_fields:
            raise ValueError(
                f"{selector}: policy fields missing from CheckPolicies: "
                f"{sorted(missing_fields)}"
            )
        checks.append(
            BuiltinCheck(
                selector=selector,
                policy_field=spec.policy_field,
                policy_inputs_observed=observed_fields,
                policy_fields=tuple(
                    PolicyField(name, field_types[name]) for name in observed_fields
                ),
                runner=f"{binding.module}:{binding.name}",
                output_shape=spec.output_shape,
                result_adapter=(
                    "alphus.execution.results:RuleEvaluation.from_output/"
                    f"{spec.output_shape}"
                ),
                requires_files=spec.requires_files,
            )
        )
    return BuiltinInventory(
        schema_version=1,
        purpose="generated current-state audit; not a registration source",
        policy_input_observation=(
            "primary RuleSpec field plus direct config.checks references in the "
            "runner literal or mapped local function; imported helpers and "
            "indirect aliases are not followed"
        ),
        shared_selection_surfaces=SelectionSurfaces(
            direct_cli="--rule SELECTOR",
            profile="RuleRunStep.rule",
        ),
        shared_reporting_surfaces=ReportingSurfaces(
            direct_cli="alphus.cli shape-dispatched legacy renderer",
            profile="RuleEvaluation diagnostics and threshold decision",
            catalog="alphus --catalog and --catalog --json",
        ),
        selector_count_source="alphus.policy.catalog.RULE_SPECS",
        selector_count=len(checks),
        checks=tuple(checks),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="repository root")
    parser.add_argument("--output", type=Path, help="output JSON path")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check and args.output is None:
        parser.error("--check requires --output")
    try:
        expected = (
            json.dumps(asdict(inventory(args.root)), indent=2, sort_keys=True) + "\n"
        )
    except (OSError, SyntaxError, TypeError, ValueError) as error:
        print(f"built-in inventory generation failed: {error}", file=sys.stderr)
        return 1
    if args.check:
        target = args.output
        if target is None:
            return 2
        if not target.is_file() or target.read_text(encoding="utf-8") != expected:
            print(f"{target} is stale; regenerate it with this script", file=sys.stderr)
            return 1
        return 0
    if args.output is None:
        sys.stdout.write(expected)
        return 0
    target = args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
