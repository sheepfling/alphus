"""Advisory Pydantic source patterns with no consumer-specific model names."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path

from alphus.config import PydanticPracticePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_scanning import (
    ImportAliases,
    canonical_expression_name,
    import_aliases,
)
from alphus.support.source_text import read_python_source

_DUMP_METHODS = frozenset({"model_dump", "model_dump_json"})
_VALIDATION_METHODS = frozenset(
    {"model_validate", "model_validate_json", "validate_python", "validate_json"}
)
_V1_DECORATORS = frozenset(
    {
        "pydantic.validator",
        "pydantic.root_validator",
        "pydantic.v1.validator",
        "pydantic.v1.root_validator",
    }
)
_V1_FUNCTIONS = frozenset({"pydantic.parse_obj_as", "pydantic.v1.parse_obj_as"})
_V1_METHODS = frozenset(
    {"parse_obj", "parse_raw", "parse_file", "from_orm", "dict", "json", "schema"}
)
_FASTAPI_FACTORY_NAMES = frozenset(
    {
        "fastapi.FastAPI",
        "fastapi.APIRouter",
        "fastapi.applications.FastAPI",
        "fastapi.routing.APIRouter",
    }
)
_FASTAPI_ROUTE_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace", "api_route"}
)


def _names(target: ast.expr) -> set[str]:
    match target:
        case ast.Name(id=name):
            return {name}
        case ast.Tuple(elts=items) | ast.List(elts=items):
            return {name for item in items for name in _names(item)}
        case _:
            return set()


def _contains_dump(expression: ast.AST, dumped: AbstractSet[str]) -> bool:
    for node in ast.walk(expression):
        match node:
            case ast.Call(func=ast.Attribute(attr=method)) if method in _DUMP_METHODS:
                return True
            case ast.Name(id=name, ctx=ast.Load()) if name in dumped:
                return True
            case _:
                pass
    return False


def _literal_bool(value: ast.expr) -> bool:
    match value:
        case ast.Constant(value=bool()):
            return True
        case _:
            return False


class _DumpFlow(ast.NodeVisitor):
    """Follow visible local assignments in one function, without nested scopes."""

    def __init__(self) -> None:
        self.dumped: set[str] = set()
        self.lines: set[int] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Nested functions have their own local assignment state."""

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """A nested class is another source scope."""

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        targets = {name for target in node.targets for name in _names(target)}
        if _contains_dump(node.value, self.dumped):
            self.dumped.update(targets)
        else:
            self.dumped.difference_update(targets)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            return
        self.visit(node.value)
        targets = _names(node.target)
        if _contains_dump(node.value, self.dumped):
            self.dumped.update(targets)
        else:
            self.dumped.difference_update(targets)

    def visit_Call(self, node: ast.Call) -> None:
        match node.func:
            case ast.Attribute(attr=method) if method in _VALIDATION_METHODS:
                values = (*node.args, *(keyword.value for keyword in node.keywords))
                if any(_contains_dump(value, self.dumped) for value in values):
                    self.lines.add(node.lineno)
            case _:
                pass
        self.generic_visit(node)


def _dump_revalidation_lines(module: ast.Module) -> list[int]:
    lines: set[int] = set()
    for node in ast.walk(module):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                flow = _DumpFlow()
                for statement in node.body:
                    flow.visit(statement)
                lines.update(flow.lines)
            case _:
                pass
    return sorted(lines)


def _explicit_frozen(node: ast.ClassDef, aliases: ImportAliases) -> bool:
    # A class keyword is a supported Pydantic v2 configuration form.
    if any(
        keyword.arg == "frozen" and _literal_bool(keyword.value)
        for keyword in node.keywords
    ):
        return True
    for statement in node.body:
        match statement:
            case ast.Assign(targets=targets, value=value) if any(
                "model_config" in _names(target) for target in targets
            ):
                pass
            case ast.AnnAssign(target=ast.Name(id="model_config"), value=value):
                pass
            case _:
                continue
        match value:
            case ast.Call(func=function, keywords=keywords) if (
                canonical_expression_name(function, aliases) == "pydantic.ConfigDict"
            ):
                if any(
                    item.arg == "frozen" and _literal_bool(item.value)
                    for item in keywords
                ):
                    return True
            case ast.Dict(keys=keys, values=values):
                if any(
                    _frozen_entry(key, item)
                    for key, item in zip(keys, values, strict=True)
                ):
                    return True
            case _:
                pass
    return False


def _frozen_entry(key: ast.expr | None, value: ast.expr) -> bool:
    match (key, value):
        case (ast.Constant(value="frozen"), ast.Constant(value=bool())):
            return True
        case _:
            return False


def _model_base(
    base: ast.expr, aliases: ImportAliases, local_models: AbstractSet[str]
) -> bool:
    if canonical_expression_name(base, aliases) in {
        "pydantic.BaseModel",
        "pydantic.v1.BaseModel",
    }:
        return True
    match base:
        case ast.Name(id=name):
            return name in local_models
        case _:
            return False


def _implicit_mutability_lines(module: ast.Module) -> list[int]:
    aliases = import_aliases(module)
    local_models: set[str] = set()
    lines: list[int] = []
    for node in module.body:
        match node:
            case ast.ClassDef():
                if not any(
                    _model_base(base, aliases, local_models) for base in node.bases
                ):
                    continue
                local_models.add(node.name)
                if not _explicit_frozen(node, aliases):
                    lines.append(node.lineno)
            case _:
                pass
    return lines


def _model_names(module: ast.Module, aliases: ImportAliases) -> set[str]:
    models: set[str] = set()
    for node in module.body:
        match node:
            case ast.ClassDef(name=name, bases=bases) if any(
                _model_base(base, aliases, models) for base in bases
            ):
                models.add(name)
            case _:
                pass
    return models


class _ScopeNamesAndCalls(ast.NodeVisitor):
    """Collect same-scope calls and bindings without entering child scopes."""

    def __init__(self, methods: AbstractSet[str]) -> None:
        self.methods = methods
        self.calls: list[ast.Call] = []
        self.bound_names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        match node.ctx:
            case ast.Store() | ast.Del():
                self.bound_names.add(node.id)
            case _:
                pass

    def visit_Call(self, node: ast.Call) -> None:
        match node.func:
            case ast.Attribute(attr=method) if method in self.methods:
                self.calls.append(node)
            case _:
                pass
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.bound_names.update(
            alias.asname or alias.name.split(".")[0] for alias in node.names
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.bound_names.update(
            alias.asname or alias.name for alias in node.names if alias.name != "*"
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.bound_names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.bound_names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bound_names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """A lambda is a child scope with independent local bindings."""


def _binding_names(statements: Sequence[ast.stmt]) -> set[str]:
    visitor = _ScopeNamesAndCalls(frozenset())
    for statement in statements:
        visitor.visit(statement)
    return visitor.bound_names


def _update_model_aliases(
    statement: ast.stmt, aliases: AbstractSet[str], models: AbstractSet[str]
) -> set[str]:
    updated = set(aliases)
    match statement:
        case ast.Assign(targets=targets, value=ast.Name(id=source)):
            names = {name for target in targets for name in _names(target)}
            updated.difference_update(names)
            if source in aliases or source in models:
                updated.update(names)
        case ast.Assign(targets=targets):
            updated.difference_update(
                name for target in targets for name in _names(target)
            )
        case ast.AnnAssign(target=target, value=ast.Name(id=source)):
            names = _names(target)
            updated.difference_update(names)
            if source in aliases or source in models:
                updated.update(names)
        case ast.AnnAssign(target=target):
            updated.difference_update(_names(target))
        case ast.AugAssign(target=target):
            updated.difference_update(_names(target))
        case _:
            pass
    return updated


def _scan_model_call_statements(
    statements: Sequence[ast.stmt],
    aliases: AbstractSet[str],
    models: AbstractSet[str],
    methods: AbstractSet[str],
    update_required: bool,
    *,
    top_level: bool = False,
) -> set[int]:
    lines: set[int] = set()
    model_aliases = set(aliases)
    for statement in statements:
        match statement:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                model_aliases = model_aliases.difference({name})
                continue
            case ast.ClassDef(name=name) if top_level and name in models:
                model_aliases = model_aliases.union({name})
                continue
            case ast.ClassDef(name=name):
                model_aliases = model_aliases.difference({name})
                continue
            case _:
                pass
        visitor = _ScopeNamesAndCalls(methods)
        visitor.visit(statement)
        match statement:
            case ast.Assign() | ast.AnnAssign():
                direct_assignment = True
            case _:
                direct_assignment = False
        uncertain: set[str] = set()
        if not direct_assignment:
            uncertain = model_aliases.intersection(visitor.bound_names)
        for call in visitor.calls:
            match call.func:
                case ast.Attribute(value=ast.Name(id=receiver), attr=method) if (
                    receiver in model_aliases and receiver not in uncertain
                ):
                    if (
                        update_required
                        and method == "model_copy"
                        and not any(
                            keyword.arg == "update" for keyword in call.keywords
                        )
                    ):
                        continue
                    lines.add(call.lineno)
                case _:
                    pass
        model_aliases = _update_model_aliases(statement, model_aliases, models)
        if not direct_assignment:
            model_aliases = model_aliases.difference(visitor.bound_names)
    return lines


def _function_model_call_lines(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    models: AbstractSet[str],
    methods: AbstractSet[str],
    *,
    model_method: bool,
    update_required: bool,
) -> set[int]:
    arguments = [
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
    ]
    local_names = _binding_names(node.body)
    aliases = set(models).difference(local_names)
    for argument in arguments:
        match argument.annotation:
            case ast.Name(id=name) if name in models:
                aliases.add(argument.arg)
            case _:
                pass
    if model_method and arguments and arguments[0].arg in {"self", "cls"}:
        aliases.add(arguments[0].arg)
    return _scan_model_call_statements(
        node.body, aliases, models, methods, update_required
    )


def _model_method_lines(
    module: ast.Module,
    models: AbstractSet[str],
    methods: AbstractSet[str],
    *,
    update_required: bool = False,
) -> list[int]:
    lines = _scan_model_call_statements(
        module.body,
        set(models),
        models,
        methods,
        update_required,
        top_level=True,
    )
    model_method_nodes: set[ast.FunctionDef | ast.AsyncFunctionDef] = set()
    for statement in module.body:
        match statement:
            case ast.ClassDef(name=name, body=body) if name in models:
                for member in body:
                    match member:
                        case ast.FunctionDef() | ast.AsyncFunctionDef():
                            model_method_nodes.add(member)
                        case _:
                            pass
            case _:
                pass
    for node in ast.walk(module):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                lines.update(
                    _function_model_call_lines(
                        node,
                        models,
                        methods,
                        model_method=node in model_method_nodes,
                        update_required=update_required,
                    )
                )
            case _:
                pass
    return sorted(lines)


def _new_api_lines(
    module: ast.Module, models: AbstractSet[str], method: str
) -> list[int]:
    return _model_method_lines(
        module,
        models,
        frozenset({method}),
        update_required=method == "model_copy",
    )


def _deprecated_v1_lines(
    module: ast.Module, aliases: ImportAliases, models: AbstractSet[str]
) -> list[int]:
    lines = set(_model_method_lines(module, models, _V1_METHODS))
    for node in ast.walk(module):
        match node:
            case (
                ast.FunctionDef(decorator_list=decorators)
                | ast.AsyncFunctionDef(decorator_list=decorators)
            ):
                deprecated = [
                    decorator
                    for decorator in decorators
                    if _decorator_name(decorator, aliases) in _V1_DECORATORS
                ]
                lines.update(decorator.lineno for decorator in deprecated)
            case ast.ClassDef(name=name, body=body) if name in models:
                for statement in body:
                    match statement:
                        case ast.ClassDef(name="Config", lineno=line):
                            lines.add(line)
                        case _:
                            pass
            case ast.Call(func=function, lineno=line) if (
                canonical_expression_name(function, aliases) in _V1_FUNCTIONS
            ):
                lines.add(line)
            case _:
                pass
    return sorted(lines)


def _decorator_name(decorator: ast.expr, aliases: ImportAliases) -> str | None:
    match decorator:
        case ast.Call(func=function):
            return canonical_expression_name(function, aliases)
        case _:
            return canonical_expression_name(decorator, aliases)


def _field_positional_lines(
    module: ast.Module, aliases: ImportAliases, models: AbstractSet[str]
) -> list[int]:
    lines: set[int] = set()
    for statement in module.body:
        match statement:
            case ast.ClassDef(name=name, body=body) if name in models:
                pass
            case _:
                continue
        for field in body:
            match field:
                case ast.AnnAssign(annotation=annotation, value=value):
                    expressions = [annotation]
                    if value is not None:
                        expressions.append(value)
                case _:
                    continue
            for expression in expressions:
                for node in ast.walk(expression):
                    match node:
                        case ast.Call(
                            func=function,
                            args=args,
                            keywords=keywords,
                            lineno=line,
                        ) if (
                            canonical_expression_name(function, aliases)
                            == "pydantic.Field"
                            and args
                            and not any(
                                keyword.arg == "default" for keyword in keywords
                            )
                        ):
                            lines.add(line)
                        case _:
                            pass
    return sorted(lines)


def _validator_can_fallthrough(statements: Sequence[ast.stmt]) -> bool:
    """Return true only for simple suites with a reachable implicit exit."""
    for statement in statements:
        match statement:
            case ast.Return() | ast.Raise():
                return False
            case ast.If(body=body, orelse=orelse):
                body_falls_through = _validator_can_fallthrough(body)
                else_falls_through = (
                    True if not orelse else _validator_can_fallthrough(orelse)
                )
                if body_falls_through or else_falls_through:
                    continue
                return False
            case (
                ast.For()
                | ast.AsyncFor()
                | ast.While()
                | ast.Try()
                | ast.Match()
                | ast.With()
                | ast.AsyncWith()
            ):
                return False
            case _:
                pass
    return True


def _validator_fallthrough_lines(
    module: ast.Module, aliases: ImportAliases
) -> list[int]:
    lines: list[int] = []
    accepted = {"pydantic.field_validator", "pydantic.model_validator"}
    for node in ast.walk(module):
        match node:
            case ast.FunctionDef(decorator_list=decorators, body=body, lineno=line):
                pass
            case ast.AsyncFunctionDef(
                decorator_list=decorators, body=body, lineno=line
            ):
                pass
            case _:
                continue
        if any(
            _decorator_name(decorator, aliases) in accepted for decorator in decorators
        ) and _validator_can_fallthrough(body):
            lines.append(line)
    return sorted(lines)


def _fastapi_owners(module: ast.Module, aliases: ImportAliases) -> set[str]:
    owners: set[str] = set()
    for statement in module.body:
        match statement:
            case ast.Assign(targets=targets, value=ast.Call(func=function)):
                if (
                    canonical_expression_name(function, aliases)
                    in _FASTAPI_FACTORY_NAMES
                ):
                    for target in targets:
                        match target:
                            case ast.Name(id=name):
                                owners.add(name)
                            case _:
                                pass
            case ast.AnnAssign(target=ast.Name(id=name), value=ast.Call(func=function)):
                if (
                    canonical_expression_name(function, aliases)
                    in _FASTAPI_FACTORY_NAMES
                ):
                    owners.add(name)
            case _:
                pass
    return owners


def _external_models(
    module: ast.Module,
    aliases: ImportAliases,
    models: AbstractSet[str],
    configured: AbstractSet[str],
) -> set[str]:
    external = set(models).intersection(configured)
    owners = _fastapi_owners(module, aliases)
    for node in module.body:
        match node:
            case ast.FunctionDef(decorator_list=decorators, returns=returns, args=args):
                pass
            case ast.AsyncFunctionDef(
                decorator_list=decorators, returns=returns, args=args
            ):
                pass
            case _:
                continue
        is_route = False
        exposed_expressions: list[ast.expr] = []
        for decorator in decorators:
            match decorator:
                case ast.Call(
                    func=ast.Attribute(value=ast.Name(id=owner), attr=method),
                    keywords=keywords,
                ) if owner in owners and method in _FASTAPI_ROUTE_METHODS:
                    is_route = True
                    exposed_expressions.extend(
                        keyword.value
                        for keyword in keywords
                        if keyword.arg in {"response_model", "responses"}
                    )
                case _:
                    continue
        if not is_route:
            continue
        if returns is not None:
            exposed_expressions.append(returns)
        exposed_expressions.extend(
            argument.annotation
            for argument in [
                *args.posonlyargs,
                *args.args,
                *args.kwonlyargs,
            ]
            if argument.annotation is not None
        )
        for expression in exposed_expressions:
            for candidate in ast.walk(expression):
                match candidate:
                    case ast.Name(id=name) if name in models:
                        external.add(name)
                    case _:
                        pass
    classes: dict[str, ast.ClassDef] = {}
    for node in module.body:
        match node:
            case ast.ClassDef(name=name):
                classes[name] = node
            case _:
                pass
    pending = list(external)
    while pending:
        model = classes.get(pending.pop())
        if model is None:
            continue
        for base in model.bases:
            match base:
                case ast.Name(id=name) if name in models and name not in external:
                    external.add(name)
                    pending.append(name)
                case _:
                    pass
        for statement in model.body:
            match statement:
                case ast.AnnAssign(annotation=annotation):
                    for candidate in ast.walk(annotation):
                        match candidate:
                            case ast.Name(id=name) if (
                                name in models and name not in external
                            ):
                                external.add(name)
                                pending.append(name)
                            case _:
                                pass
                case _:
                    pass
    return external


def _field_has_description(expression: ast.AST, aliases: ImportAliases) -> bool:
    for node in ast.walk(expression):
        match node:
            case ast.Call(func=function, keywords=keywords) if (
                canonical_expression_name(function, aliases)
                in {"pydantic.Field", "pydantic.fields.Field"}
            ):
                pass
            case _:
                continue
        description = next(
            (keyword.value for keyword in keywords if keyword.arg == "description"),
            None,
        )
        if description is not None and _descriptive_expression(description):
            return True
        for keyword in keywords:
            if keyword.arg != "json_schema_extra":
                continue
            match keyword.value:
                case ast.Dict() as extra if _dict_has_description(extra):
                    return True
                case ast.Dict():
                    pass
                case _:
                    return True
    return False


def _descriptive_expression(value: ast.expr) -> bool:
    match value:
        case ast.Constant(value=str() as description):
            return bool(description.strip())
        case ast.Constant():
            return False
        case _:
            return True


def _dict_has_description(value: ast.Dict) -> bool:
    for key, item in zip(value.keys, value.values, strict=True):
        match key:
            case ast.Constant(value="description") if _descriptive_expression(item):
                return True
            case _:
                pass
    return False


def _dict_values(value: ast.Dict, name: str) -> list[ast.expr]:
    result: list[ast.expr] = []
    for key, item in zip(value.keys, value.values, strict=True):
        match key:
            case ast.Constant(value=key_name) if key_name == name:
                result.append(item)
            case _:
                pass
    return result


def _model_has_schema_description(node: ast.ClassDef, aliases: ImportAliases) -> bool:
    docstring = ast.get_docstring(node, clean=False)
    if docstring and docstring.strip():
        return True
    for statement in node.body:
        value: ast.expr | None = None
        match statement:
            case ast.Assign(targets=targets, value=assigned) if any(
                "model_config" in _names(target) for target in targets
            ):
                value = assigned
            case ast.AnnAssign(target=ast.Name(id="model_config"), value=assigned):
                value = assigned
            case _:
                pass
        if value is None:
            continue
        match value:
            case ast.Dict() as config:
                config_values = _dict_values(config, "json_schema_extra")
            case ast.Call(func=function, keywords=keywords) if (
                canonical_expression_name(function, aliases)
                in {"pydantic.ConfigDict", "pydantic.config.ConfigDict"}
            ):
                config_values = [
                    keyword.value
                    for keyword in keywords
                    if keyword.arg == "json_schema_extra"
                ]
            case _:
                continue
        for config_value in config_values:
            match config_value:
                case ast.Dict() as extra:
                    if _dict_has_description(extra):
                        return True
                case _:
                    return True
    return False


def _external_model_doc_lines(
    module: ast.Module,
    aliases: ImportAliases,
    models: AbstractSet[str],
    configured: AbstractSet[str],
) -> list[tuple[int, str]]:
    external = _external_models(module, aliases, models, configured)
    findings: list[tuple[int, str]] = []
    for node in module.body:
        match node:
            case ast.ClassDef(name=name, body=body, lineno=line) if name in external:
                pass
            case _:
                continue
        if not _model_has_schema_description(node, aliases):
            findings.append(
                (
                    line,
                    "add a class description for this external model's JSON Schema",
                )
            )
        for statement in body:
            match statement:
                case ast.AnnAssign(
                    target=ast.Name(id=field_name),
                    annotation=annotation,
                    value=value,
                    lineno=field_line,
                ):
                    pass
                case _:
                    continue
            if field_name == "model_config" or field_name.startswith("_"):
                continue
            class_variable = False
            for part in ast.walk(annotation):
                match part:
                    case ast.Name() | ast.Attribute() if canonical_expression_name(
                        part, aliases
                    ) in {
                        "typing.ClassVar",
                        "typing_extensions.ClassVar",
                        "pydantic.PrivateAttr",
                    }:
                        class_variable = True
                        break
                    case _:
                        pass
            if class_variable:
                continue
            if _field_has_description(annotation, aliases):
                continue
            if value is not None and _field_has_description(value, aliases):
                continue
            findings.append(
                (
                    field_line,
                    f"add a JSON Schema description for external field {field_name!r}",
                )
            )
    return findings


def pydantic_practice_findings(
    source: str, policy: PydanticPracticePolicy, *, path: str = "<source>"
) -> list[Finding]:
    """Report possible redundant validation and opt-in mutability intent."""
    module = ast.parse(source, filename=path)
    aliases = import_aliases(module)
    models = _model_names(module, aliases)
    findings: list[Finding] = []
    if policy.report_dump_revalidation:
        findings.extend(
            Finding(
                rule_id=rule_tag(
                    Scope.PYTHON,
                    Framework.PYDANTIC,
                    Category.VALIDATION,
                    "dump-revalidation",
                ),
                path=path,
                line=line,
                severity="warning",
                message=(
                    "a model dump appears to be validated again; review whether "
                    "this boundary needs a second validation"
                ),
            )
            for line in _dump_revalidation_lines(module)
        )
    if policy.require_explicit_frozen:
        findings.extend(
            Finding(
                rule_id=rule_tag(
                    Scope.PYTHON,
                    Framework.PYDANTIC,
                    Category.CORRECTNESS,
                    "implicit-mutability",
                ),
                path=path,
                line=line,
                severity="warning",
                message="declare frozen=True or frozen=False on this Pydantic model",
            )
            for line in _implicit_mutability_lines(module)
        )
    optional_rules = (
        (
            policy.report_deprecated_v1_apis,
            Category.CORRECTNESS,
            "deprecated-v1-api",
            _deprecated_v1_lines(module, aliases, models),
            "review this Pydantic v1 API before migrating to v2",
        ),
        (
            policy.report_unvalidated_construct,
            Category.VALIDATION,
            "unvalidated-construct",
            _new_api_lines(module, models, "model_construct"),
            "model_construct bypasses validation; use only with trusted, prevalidated data",
        ),
        (
            policy.report_unvalidated_copy_update,
            Category.VALIDATION,
            "unvalidated-copy-update",
            _new_api_lines(module, models, "model_copy"),
            "model_copy(update=...) does not validate updated values",
        ),
        (
            policy.report_validator_fallthrough,
            Category.CORRECTNESS,
            "validator-fallthrough",
            _validator_fallthrough_lines(module, aliases),
            "this Pydantic validator may reach its end without returning a value",
        ),
        (
            policy.report_field_positional_default,
            Category.STYLE,
            "field-positional-default",
            _field_positional_lines(module, aliases, models),
            "use Field(default=...) to make the field default explicit",
        ),
    )
    for enabled, category, name, lines, message in optional_rules:
        if enabled:
            findings.extend(
                Finding(
                    rule_id=rule_tag(Scope.PYTHON, Framework.PYDANTIC, category, name),
                    path=path,
                    line=line,
                    severity="info"
                    if name == "field-positional-default"
                    else "warning",
                    message=message,
                )
                for line in lines
            )
    if policy.report_external_model_docs:
        findings.extend(
            Finding(
                rule_id=rule_tag(
                    Scope.PYTHON,
                    Framework.PYDANTIC,
                    Category.METADATA,
                    "external-schema-documentation",
                ),
                path=path,
                line=line,
                severity="info",
                message=message,
            )
            for line, message in _external_model_doc_lines(
                module, aliases, models, set(policy.external_model_names)
            )
        )
    return sorted(findings, key=lambda finding: (finding.line or 0, finding.rule_id))


def check_pydantic_practices(
    root: Path, paths: Iterable[Path], policy: PydanticPracticePolicy
) -> list[Finding]:
    """Analyze only Python files selected by the caller's repository policy."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if relative.suffix not in policy.extensions or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
        source = read_python_source(checkout / relative)
        findings.extend(pydantic_practice_findings(source, policy, path=name))
    return findings
