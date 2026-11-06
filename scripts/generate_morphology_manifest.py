"""Generate the static morphology catalog from feature-owned literal declarations.

The generator parses first-party source with ``ast`` and ``ast.literal_eval``. It
never imports check modules or executes repository code.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_DECLARATION_NAME = "ALPHUS_MORPHOLOGY"
_CHECK_DECLARATION_NAME = "ALPHUS_CHECK"
_COMPLAINT_CONTRACTS_NAME = "ALPHUS_COMPLAINT_CONTRACTS"
_DECLARATION_COMMON_FIELDS: frozenset[str] = frozenset(
    {
        "selector",
        "concern",
        "claim_kind",
        "claim",
        "mechanisms",
        "inspected_scope",
        "languages_formats",
        "evidence_kinds",
        "evaluation_maturity",
    }
)
_DIRECT_FINDING_FIELD = "finding_tag_complaints"
_CONTRACT_FINDING_FIELD = "finding_contracts"
_MECHANISMS = frozenset(
    {
        "exact-rule",
        "bounded-heuristic",
        "native-tool",
        "local-model-assisted",
    }
)
_CLAIM_KINDS = frozenset({"condition", "risk", "style-preference"})
_MATURITY = frozenset(
    {"unassessed", "synthetic-only", "public-sample-reviewed", "human-evaluated"}
)
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_TARGET = Path("src/alphus/policy/_generated_morphology.py")
_FEATURE_TARGET = Path("src/alphus/policy/_generated_feature_definitions.py")
_FEATURE_POLICIES_TARGET = Path("src/alphus/policy/_generated_feature_policies.py")
_QUALITY_RULES_TARGET = Path("src/alphus/policy/_generated_quality_rule_names.py")
_MAX_FEATURE_MODULES = 2048
_MAX_SOURCE_MODULE_BYTES = 1_048_576
_MAX_SCANNED_SOURCE_BYTES = 16_777_216


def _valid_domain_values(values: tuple[object, ...]) -> bool:
    for value in values:
        match value:
            case str(domain) if _SLUG.fullmatch(domain) is not None:
                continue
            case _:
                return False
    return True


@dataclass(frozen=True, slots=True)
class _FeatureRegistration:
    selector: str
    policy_field: str
    policy_model: str
    output_shape: str
    summary: str
    applies_to: tuple[str, ...]
    domains: tuple[str, ...]
    requires_files: bool
    runner_module: str
    runner_name: str


@dataclass(frozen=True, slots=True)
class _FindingContract:
    name: str
    emitters: tuple[str, ...]
    rule_ids_by_emitter: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _Declaration:
    selector: str
    finding_ids: tuple[str, ...]
    finding_contracts: tuple[str, ...]
    concern: str
    claim_kind: str
    claim: str
    mechanisms: tuple[str, ...]
    inspected_scope: tuple[str, ...]
    languages_formats: tuple[str, ...]
    evidence_kinds: tuple[str, ...]
    evaluation_maturity: str
    source: str
    feature: _FeatureRegistration | None = None


def _assignment_name(statement: ast.stmt) -> str | None:
    match statement:
        case ast.AnnAssign(target=ast.Name(id=name)):
            return name
        case ast.Assign(targets=[ast.Name(id=name), *_]):
            return name
        case _:
            return None


def _assignment_value(statement: ast.stmt) -> ast.expr | None:
    match statement:
        case ast.AnnAssign(value=value) | ast.Assign(value=value):
            return value
        case _:
            return None


def _static_rule_ids(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    result: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        match node:
            case ast.Call(
                func=ast.Name(id="rule_tag"),
                args=[
                    ast.Attribute(value=ast.Name(), attr=scope),
                    ast.Attribute(value=ast.Name(), attr=framework),
                    ast.Attribute(value=ast.Name(), attr=category),
                    ast.Constant(value=str(complaint)),
                ],
                keywords=[],
            ):
                rule_id = (
                    f"alphus/{scope.lower()}/{framework.lower()}/{category.lower()}"
                    f"/{complaint}"
                )
                result.setdefault(complaint, set()).add(rule_id)
            case _:
                pass
    return {
        complaint: tuple(sorted(rule_ids)) for complaint, rule_ids in result.items()
    }


def _enum_values(root: Path, enum_name: str) -> frozenset[str]:
    tags_path = root / "src" / "alphus" / "contracts" / "rule_tags.py"
    tree = ast.parse(tags_path.read_text(encoding="utf-8"), filename=str(tags_path))
    for statement in tree.body:
        if not isinstance(statement, ast.ClassDef) or statement.name != enum_name:
            continue
        values: set[str] = set()
        for member in statement.body:
            if not isinstance(member, ast.Assign) or len(member.targets) != 1:
                continue
            if not isinstance(member.targets[0], ast.Name):
                continue
            value_node = member.value
            if isinstance(value_node, ast.Constant):
                value: str | bytes = cast(str | bytes, value_node.value)
                if type(value) is str:
                    values.add(value)
        if values:
            return frozenset(values)
    raise ValueError(f"{tags_path}: missing string enum {enum_name}")


def _parse_rule_id(root: Path, value: object, source: Path) -> str:
    candidate: str | bytes = cast(str | bytes, value)
    if type(candidate) is not str:
        raise ValueError(f"{source}: complaint contract rule IDs must be strings")
    parts = candidate.split("/")
    if len(parts) != 5 or parts[0] != "alphus":
        raise ValueError(f"{source}: invalid complaint contract rule ID {candidate!r}")
    scope, framework, category, complaint = parts[1:]
    if (
        scope not in _enum_values(root, "Scope")
        or framework not in _enum_values(root, "Framework")
        or category not in _enum_values(root, "Category")
        or not _SLUG.fullmatch(complaint)
    ):
        raise ValueError(f"{source}: invalid complaint contract rule ID {candidate!r}")
    return candidate


def _static_rule_id(root: Path, node: ast.expr, source: Path) -> str:
    match node:
        case ast.Call(
            func=ast.Name(id="rule_tag"),
            args=[
                ast.Attribute(value=ast.Name(id="Scope"), attr=scope),
                ast.Attribute(value=ast.Name(id="Framework"), attr=framework),
                ast.Attribute(value=ast.Name(id="Category"), attr=category),
                ast.Constant(value=complaint),
            ],
            keywords=[],
        ):
            complaint_value: str | bytes = cast(str | bytes, complaint)
            if type(complaint_value) is not str:
                raise ValueError(
                    f"{source}: rule_tag complaint must be a string literal"
                )
            candidate = (
                f"alphus/{scope.lower()}/{framework.lower()}/{category.lower()}/"
                f"{complaint_value}"
            )
        case _:
            raise ValueError(f"{source}: complaint contracts must use rule_tag calls")
    return _parse_rule_id(root, candidate, source)


def _static_complaint_contracts(
    root: Path, paths: Sequence[Path]
) -> dict[str, _FindingContract]:
    contracts: dict[str, _FindingContract] = {}
    rule_id_owners: dict[str, str] = {}
    runtime_tag_owners: dict[tuple[str, str, str, str], str] = {}
    for path in paths:
        source = path.read_text(encoding="utf-8")
        if _COMPLAINT_CONTRACTS_NAME not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        assignments = [
            _assignment_value(statement)
            for statement in tree.body
            if _assignment_name(statement) == _COMPLAINT_CONTRACTS_NAME
        ]
        if len(assignments) != 1 or assignments[0] is None:
            raise ValueError(
                f"{path} must define exactly one {_COMPLAINT_CONTRACTS_NAME} literal"
            )
        raw_records = assignments[0]
        if not isinstance(raw_records, ast.Tuple):
            raise TypeError(f"{path}:{_COMPLAINT_CONTRACTS_NAME} must be a tuple")
        for record in raw_records.elts:
            if not isinstance(record, ast.Tuple) or len(record.elts) != 3:
                raise ValueError(
                    f"{path}:{_COMPLAINT_CONTRACTS_NAME} entries must be triples"
                )
            name_raw: object = ast.literal_eval(record.elts[0])
            name_value: str | bytes = cast(str | bytes, name_raw)
            if type(name_value) is not str or not _SLUG.fullmatch(name_value):
                raise ValueError(
                    f"{path}: invalid complaint contract name {name_raw!r}"
                )
            if name_value in contracts:
                raise ValueError(f"{path}: duplicate complaint contract {name_value!r}")
            raw_emitters: object = ast.literal_eval(record.elts[1])
            emitters = _string_tuple(raw_emitters, "complaint contract emitters")
            if any(not _SLUG.fullmatch(emitter) for emitter in emitters):
                raise ValueError(f"{path}: complaint contract emitters must be slugs")
            tag_records = record.elts[2]
            if not isinstance(tag_records, ast.Tuple) or not tag_records.elts:
                raise ValueError(f"{path}: complaint contract tags must be a tuple")
            tags: list[tuple[str, str]] = []
            for tag_record in tag_records.elts:
                if not isinstance(tag_record, ast.Tuple) or len(tag_record.elts) != 2:
                    raise ValueError(f"{path}: complaint contract tags must be pairs")
                emitter_raw: object = ast.literal_eval(tag_record.elts[0])
                emitter_value: str | bytes = cast(str | bytes, emitter_raw)
                if type(emitter_value) is not str or emitter_value not in emitters:
                    raise ValueError(
                        f"{path}: complaint tag emitter must be declared by its contract"
                    )
                rule_id = _static_rule_id(root, tag_record.elts[1], path)
                if (emitter_value, rule_id) in tags:
                    raise ValueError(
                        f"{path}: duplicate complaint tag for {emitter_value!r}"
                    )
                previous_contract = rule_id_owners.get(rule_id)
                if previous_contract is not None and previous_contract != name_value:
                    raise ValueError(
                        f"{path}: rule ID {rule_id!r} belongs to multiple complaint contracts"
                    )
                rule_id_owners[rule_id] = name_value
                _, scope, framework, _, complaint = rule_id.split("/")
                runtime_key = (emitter_value, scope, framework, complaint)
                previous_runtime_tag = runtime_tag_owners.get(runtime_key)
                if previous_runtime_tag is not None:
                    raise ValueError(
                        f"{path}: complaint contract {name_value!r} has ambiguous "
                        f"runtime tag lookup for {runtime_key!r}"
                    )
                runtime_tag_owners[runtime_key] = rule_id
                tags.append((emitter_value, rule_id))
            if set(emitters) != {emitter for emitter, _ in tags}:
                raise ValueError(
                    f"{path}: every complaint contract emitter must declare a rule ID"
                )
            contracts[name_value] = _FindingContract(
                name=name_value,
                emitters=emitters,
                rule_ids_by_emitter=tuple(tags),
            )
    return contracts


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    candidate: tuple[object, ...] | list[object] = cast(
        tuple[object, ...] | list[object], value
    )
    if type(candidate) is not tuple or not candidate:
        raise ValueError(f"{field} must be a non-empty immutable tuple of strings")
    result: list[str] = []
    items = candidate
    for item in items:
        string_item: str | bytes = cast(str | bytes, item)
        if type(string_item) is not str:
            raise TypeError(f"{field} must contain only strings")
        result.append(string_item)
    values = tuple(result)
    if len(values) != len(set(values)):
        raise ValueError(f"{field} must not contain duplicates")
    return values


def _validate_declaration(
    value: object,
    path: Path,
    *,
    feature_owned: bool = False,
    complaint_contracts: Mapping[str, _FindingContract],
) -> _Declaration:
    candidate: tuple[object, ...] | list[object] = cast(
        tuple[object, ...] | list[object], value
    )
    if type(candidate) is not tuple:
        raise TypeError(f"{path}:{_DECLARATION_NAME} must be an immutable tuple")
    raw_pairs = candidate
    pairs: list[tuple[str, object]] = []
    for raw_pair in raw_pairs:
        pair_candidate: tuple[object, ...] | list[object] = cast(
            tuple[object, ...] | list[object], raw_pair
        )
        if type(pair_candidate) is not tuple:
            raise TypeError(f"{path}:{_DECLARATION_NAME} entries must be pairs")
        pair = pair_candidate
        key_candidate: str | bytes = cast(str | bytes, pair[0] if pair else None)
        if len(pair) != 2 or type(key_candidate) is not str:
            raise ValueError(
                f"{path}:{_DECLARATION_NAME} entries must have string keys"
            )
        pairs.append((key_candidate, pair[1]))
    keys = frozenset(key for key, _ in pairs)
    feature_fields: frozenset[str] = frozenset(
        {
            "policy_field",
            "policy_model",
            "output_shape",
            "summary",
            "applies_to",
            "domains",
            "requires_files",
            "runner_module",
            "runner_name",
        }
    )
    declaration_fields: frozenset[str] = _DECLARATION_COMMON_FIELDS | (
        feature_fields if feature_owned else frozenset[str]()
    )
    valid_fields: tuple[frozenset[str], frozenset[str]] = (
        declaration_fields | {_DIRECT_FINDING_FIELD},
        declaration_fields | {_CONTRACT_FINDING_FIELD},
    )
    if len(keys) != len(pairs) or keys not in valid_fields:
        raise ValueError(
            f"{path}:{_CHECK_DECLARATION_NAME if feature_owned else _DECLARATION_NAME} "
            "must contain common fields and exactly one finding declaration "
            "field with unique keys"
        )

    def field(name: str) -> object:
        for key, item in pairs:
            if key == name:
                return item
        raise ValueError(f"{path}: missing declaration field {name!r}")

    selector_value = field("selector")
    concern_value = field("concern")
    claim_value = field("claim")
    claim_kind_value = field("claim_kind")
    selector_text: str | bytes = cast(str | bytes, selector_value)
    if type(selector_text) is not str or not _SLUG.fullmatch(selector_text):
        raise ValueError(f"{path}: selector must be a lowercase slug")
    concern_text: str | bytes = cast(str | bytes, concern_value)
    if type(concern_text) is not str or not _SLUG.fullmatch(concern_text):
        raise ValueError(f"{path}: concern must be a lowercase slug")
    claim_text: str | bytes = cast(str | bytes, claim_value)
    if type(claim_text) is not str or not claim_text.strip():
        raise ValueError(f"{path}: claim must be non-empty text")
    claim_kind_text: str | bytes = cast(str | bytes, claim_kind_value)
    if type(claim_kind_text) is not str or claim_kind_text not in _CLAIM_KINDS:
        raise ValueError(f"{path}: unsupported claim_kind {claim_kind_text!r}")

    finding_ids: tuple[str, ...] = ()
    finding_contracts: tuple[str, ...] = ()
    if _DIRECT_FINDING_FIELD in keys:
        complaints = _string_tuple(field(_DIRECT_FINDING_FIELD), _DIRECT_FINDING_FIELD)
        for complaint in complaints:
            if not _SLUG.fullmatch(complaint):
                raise ValueError(f"{path}: invalid finding complaint {complaint!r}")
        finding_ids = complaints
    else:
        finding_contracts = _string_tuple(
            field(_CONTRACT_FINDING_FIELD), _CONTRACT_FINDING_FIELD
        )
        if len(finding_contracts) != 1:
            raise ValueError(
                f"{path}: a morphology declaration must reference exactly one "
                "finding contract to keep complaint ownership unambiguous"
            )
        for contract_name in finding_contracts:
            if contract_name not in complaint_contracts:
                raise ValueError(f"{path}: unknown finding contract {contract_name!r}")
            if selector_text not in complaint_contracts[contract_name].emitters:
                raise ValueError(
                    f"{path}: selector {selector_text!r} is not a permitted emitter "
                    f"for finding contract {contract_name!r}"
                )
    inspected_scope = _string_tuple(field("inspected_scope"), "inspected_scope")
    languages_formats = _string_tuple(field("languages_formats"), "languages_formats")
    evidence_kinds = _string_tuple(field("evidence_kinds"), "evidence_kinds")
    for field_name, values in (
        ("inspected_scope", inspected_scope),
        ("languages_formats", languages_formats),
        ("evidence_kinds", evidence_kinds),
    ):
        if any(not _SLUG.fullmatch(item) for item in values):
            raise ValueError(f"{path}: {field_name} must contain lowercase slugs")
    mechanisms = _string_tuple(field("mechanisms"), "mechanisms")
    if not set(mechanisms) <= _MECHANISMS:
        raise ValueError(f"{path}: unsupported morphology mechanism")
    maturity_value = field("evaluation_maturity")
    maturity_text: str | bytes = cast(str | bytes, maturity_value)
    if type(maturity_text) is not str or maturity_text not in _MATURITY:
        raise ValueError(f"{path}: unsupported evaluation_maturity {maturity_text!r}")
    feature: _FeatureRegistration | None = None
    if feature_owned:
        policy_field = field("policy_field")
        policy_model = field("policy_model")
        output_shape = field("output_shape")
        summary = field("summary")
        requires_files = field("requires_files")
        runner_module = field("runner_module")
        runner_name = field("runner_name")
        policy_text: str | bytes = cast(str | bytes, policy_field)
        policy_model_text: str | bytes = cast(str | bytes, policy_model)
        shape_text: str | bytes = cast(str | bytes, output_shape)
        summary_text: str | bytes = cast(str | bytes, summary)
        files_value: bool | str = cast(bool | str, requires_files)
        module_text: str | bytes = cast(str | bytes, runner_module)
        function_text: str | bytes = cast(str | bytes, runner_name)
        if (
            type(policy_text) is not str
            or re.fullmatch(r"[a-z][a-z0-9_]*", policy_text) is None
        ):
            raise ValueError(f"{path}: policy_field must be a lowercase identifier")
        if (
            type(policy_model_text) is not str
            or re.fullmatch(
                r"alphus\.policy(?:\.[a-z][a-z0-9_]*)+\.[A-Z][A-Za-z0-9]*",
                policy_model_text,
            )
            is None
        ):
            raise ValueError(f"{path}: policy_model must name a built-in policy class")
        if type(shape_text) is not str or shape_text not in {
            "findings",
            "messages",
            "python-style",
            "shared-utilities",
            "cyclomatic-report",
        }:
            raise ValueError(f"{path}: unsupported output_shape {shape_text!r}")
        if type(summary_text) is not str or not summary_text.strip():
            raise ValueError(f"{path}: summary must be non-empty text")
        if type(files_value) is not bool:
            raise ValueError(f"{path}: requires_files must be a boolean literal")
        if (
            type(module_text) is not str
            or re.fullmatch(r"alphus\.gates(?:\.[a-z][a-z0-9_]*)+", module_text) is None
        ):
            raise ValueError(f"{path}: runner_module must be a built-in gates module")
        if (
            type(function_text) is not str
            or re.fullmatch(r"[a-z_][a-z0-9_]*", function_text) is None
        ):
            raise ValueError(f"{path}: runner_name must be a function identifier")
        applies_to = _string_tuple(field("applies_to"), "applies_to")
        raw_domains: tuple[object, ...] | list[object] = cast(
            tuple[object, ...] | list[object], field("domains")
        )
        match raw_domains:
            case tuple() as domain_tuple:
                domain_items: tuple[object, ...] = domain_tuple
            case _:
                raise ValueError(f"{path}: domains must be a tuple of strings")
        if not _valid_domain_values(domain_items):
            raise ValueError(f"{path}: domains must be a tuple of strings")
        feature = _FeatureRegistration(
            selector=selector_text,
            policy_field=policy_text,
            policy_model=policy_model_text,
            output_shape=shape_text,
            summary=summary_text,
            applies_to=applies_to,
            domains=cast(tuple[str, ...], domain_items),
            requires_files=files_value,
            runner_module=module_text,
            runner_name=function_text,
        )
    return _Declaration(
        selector=selector_text,
        finding_ids=finding_ids,
        finding_contracts=finding_contracts,
        concern=concern_text,
        claim_kind=claim_kind_text,
        claim=claim_text,
        mechanisms=mechanisms,
        inspected_scope=inspected_scope,
        languages_formats=languages_formats,
        evidence_kinds=evidence_kinds,
        evaluation_maturity=maturity_text,
        source=path.as_posix(),
        feature=feature,
    )


def _declaration_records(raw: object) -> tuple[object, ...]:
    candidate: tuple[object, ...] | list[object] = cast(
        tuple[object, ...] | list[object], raw
    )
    if type(candidate) is not tuple:
        return (raw,)
    values = candidate
    first_candidate: tuple[object, ...] | list[object] = cast(
        tuple[object, ...] | list[object], values[0] if values else None
    )
    if values and type(first_candidate) is tuple:
        pair = first_candidate
        key_candidate: str | bytes = cast(str | bytes, pair[0] if pair else None)
        if len(pair) == 2 and type(key_candidate) is str:
            return (values,)
    return values


def _declarations(
    root: Path, *, require_declarations: bool = True
) -> tuple[_Declaration, ...]:
    gates = root / "src" / "alphus" / "gates"
    repository_root = root.resolve(strict=True)
    gates_root = gates.resolve(strict=True)
    if gates.is_symlink() or not gates_root.is_relative_to(repository_root):
        raise ValueError(f"built-in gates root escapes the repository: {gates}")
    declarations: list[_Declaration] = []
    paths: list[Path] = []
    for path in gates.rglob("*.py"):
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(
            gates_root
        ):
            raise ValueError(f"feature source escapes the built-in gates root: {path}")
        paths.append(path)
        if len(paths) > _MAX_FEATURE_MODULES:
            raise ValueError(
                f"feature discovery exceeds {_MAX_FEATURE_MODULES} Python modules"
            )
    paths.sort()

    scanned_bytes: int = 0
    for path in paths:
        source_size: int = path.stat().st_size
        if source_size > _MAX_SOURCE_MODULE_BYTES:
            raise ValueError(
                f"{path} exceeds the {_MAX_SOURCE_MODULE_BYTES}-byte scan limit"
            )
        scanned_bytes += source_size
        if scanned_bytes > _MAX_SCANNED_SOURCE_BYTES:
            raise ValueError(
                f"feature discovery exceeds the {_MAX_SCANNED_SOURCE_BYTES}-byte scan limit"
            )

    complaint_contracts = _static_complaint_contracts(root, paths)
    actual_scanned_bytes = 0
    for path in paths:
        source_bytes: bytes
        with path.open("rb") as source_file:
            source_bytes = source_file.read(_MAX_SOURCE_MODULE_BYTES + 1)
        if len(source_bytes) > _MAX_SOURCE_MODULE_BYTES:
            raise ValueError(
                f"{path} exceeds the {_MAX_SOURCE_MODULE_BYTES}-byte scan limit"
            )
        actual_scanned_bytes += len(source_bytes)
        if actual_scanned_bytes > _MAX_SCANNED_SOURCE_BYTES:
            raise ValueError(
                f"feature discovery exceeds the {_MAX_SCANNED_SOURCE_BYTES}-byte scan limit"
            )
        source = source_bytes.decode("utf-8")
        if _DECLARATION_NAME not in source and _CHECK_DECLARATION_NAME not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        values_by_name: dict[str, list[ast.expr]] = {
            _DECLARATION_NAME: [],
            _CHECK_DECLARATION_NAME: [],
        }
        for statement in tree.body:
            assignment_name = _assignment_name(statement)
            if assignment_name in values_by_name:
                value = _assignment_value(statement)
                if value is None:
                    raise ValueError(f"{path} must assign {assignment_name}")
                values_by_name[assignment_name].append(value)
        local_ids = _static_rule_ids(tree)
        for declaration_name, values in values_by_name.items():
            if not values:
                continue
            if len(values) != 1:
                raise ValueError(f"{path} must define exactly one {declaration_name}")
            try:
                raw: object = ast.literal_eval(values[0])
            except (ValueError, TypeError, SyntaxError) as error:
                raise ValueError(
                    f"{path}:{declaration_name} must be a literal"
                ) from error
            records = _declaration_records(raw)
            for item in records:
                declaration = _validate_declaration(
                    item,
                    path,
                    feature_owned=declaration_name == _CHECK_DECLARATION_NAME,
                    complaint_contracts=complaint_contracts,
                )
                resolved_ids: list[str] = []
                if declaration.finding_contracts:
                    contract_name = declaration.finding_contracts[0]
                    contract = complaint_contracts[contract_name]
                    resolved_ids.extend(
                        rule_id
                        for emitter, rule_id in contract.rule_ids_by_emitter
                        if emitter == declaration.selector
                    )
                    if not resolved_ids:
                        raise ValueError(
                            f"{path}: finding contract {contract_name!r} declares no "
                            f"rule IDs for {declaration.selector!r}"
                        )
                else:
                    for complaint in declaration.finding_ids:
                        matches = local_ids.get(complaint, ())
                        if not matches:
                            raise ValueError(
                                f"{path}: finding complaint {complaint!r} is not declared "
                                "by this feature"
                            )
                        if len(matches) != 1:
                            raise ValueError(
                                f"{path}: finding complaint {complaint!r} resolves to multiple "
                                f"rule tags: {matches}"
                            )
                        resolved_ids.append(matches[0])
                declarations.append(
                    _Declaration(
                        selector=declaration.selector,
                        finding_ids=tuple(resolved_ids),
                        finding_contracts=declaration.finding_contracts,
                        concern=declaration.concern,
                        claim_kind=declaration.claim_kind,
                        claim=declaration.claim,
                        mechanisms=declaration.mechanisms,
                        inspected_scope=declaration.inspected_scope,
                        languages_formats=declaration.languages_formats,
                        evidence_kinds=declaration.evidence_kinds,
                        evaluation_maturity=declaration.evaluation_maturity,
                        source=declaration.source,
                        feature=declaration.feature,
                    )
                )

    owners: dict[str, str] = {}
    finding_owners: dict[str, str] = {}
    for declaration in declarations:
        if declaration.selector in owners:
            raise ValueError(
                f"duplicate morphology selector {declaration.selector!r} in "
                f"{owners[declaration.selector]} and {declaration.source}"
            )
        owners[declaration.selector] = declaration.source
        finding_owner = (
            f"contract:{declaration.finding_contracts[0]}"
            if declaration.finding_contracts
            else f"selector:{declaration.selector}"
        )
        for finding_id in declaration.finding_ids:
            owner = finding_owners.get(finding_id)
            if owner is not None and owner != finding_owner:
                raise ValueError(
                    f"finding ID {finding_id!r} is declared by multiple owners: "
                    f"{owner!r} and {finding_owner!r}"
                )
            finding_owners[finding_id] = finding_owner
        if declaration.feature is not None:
            _validate_feature_registration(root, declaration)
    if require_declarations and not declarations:
        raise ValueError(f"no {_DECLARATION_NAME} declarations found under {gates}")
    return tuple(sorted(declarations, key=lambda item: item.selector))


def feature_registrations(root: Path) -> tuple[_FeatureRegistration, ...]:
    """Return validated static feature registrations without importing features."""
    return tuple(
        declaration.feature
        for declaration in _declarations(root, require_declarations=False)
        if declaration.feature is not None
    )


def _validate_feature_registration(root: Path, declaration: _Declaration) -> None:
    feature = declaration.feature
    if feature is None:
        return
    gates_root = (root / "src" / "alphus" / "gates").resolve(strict=True)
    module_parts = feature.runner_module.split(".")
    runner_path = root.joinpath("src", *module_parts).with_suffix(".py")
    if runner_path.is_symlink() or not runner_path.resolve(strict=True).is_relative_to(
        gates_root
    ):
        raise ValueError(
            f"{declaration.source}: feature runner escapes built-in gates: "
            f"{feature.runner_module}"
        )
    runner_tree = ast.parse(
        runner_path.read_text(encoding="utf-8"), filename=str(runner_path)
    )
    if not any(
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == feature.runner_name
        for statement in runner_tree.body
    ):
        raise ValueError(
            f"{declaration.source}: feature runner does not name a top-level "
            f"function: {feature.runner_module}:{feature.runner_name}"
        )

    policy_directory = root / "src" / "alphus" / "policy"
    repository_root = root.resolve(strict=True)
    policy_root = policy_directory.resolve(strict=True)
    if policy_directory.is_symlink() or not policy_root.is_relative_to(repository_root):
        raise ValueError(
            f"{declaration.source}: built-in policy root escapes the repository: "
            f"{policy_directory}"
        )
    orchestration_path = policy_directory / "orchestration.py"
    if orchestration_path.is_symlink() or not orchestration_path.resolve(
        strict=True
    ).is_relative_to(policy_root):
        raise ValueError(
            f"{declaration.source}: strict policy declaration escapes built-in policy: "
            f"{orchestration_path}"
        )
    orchestration_tree = ast.parse(
        orchestration_path.read_text(encoding="utf-8"),
        filename=str(orchestration_path),
    )
    legacy_fields = {
        member.target.id
        for statement in orchestration_tree.body
        if isinstance(statement, ast.ClassDef) and statement.name == "CheckPolicies"
        for member in statement.body
        if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name)
    }
    if feature.policy_field in legacy_fields:
        raise ValueError(
            f"{declaration.source}: feature policy field duplicates a legacy "
            f"CheckPolicies field: {feature.policy_field}"
        )

    policy_module, policy_class = feature.policy_model.rsplit(".", 1)
    policy_path = root.joinpath("src", *policy_module.split(".")).with_suffix(".py")
    if policy_path.is_symlink() or not policy_path.resolve(strict=True).is_relative_to(
        policy_root
    ):
        raise ValueError(
            f"{declaration.source}: feature policy model escapes built-in policy: "
            f"{feature.policy_model}"
        )
    policy_tree = ast.parse(
        policy_path.read_text(encoding="utf-8"), filename=str(policy_path)
    )
    if not any(
        isinstance(statement, ast.ClassDef) and statement.name == policy_class
        for statement in policy_tree.body
    ):
        raise ValueError(
            f"{declaration.source}: feature policy model does not name a top-level "
            f"class: {feature.policy_model}"
        )


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _tuple_lines(name: str, values: tuple[str, ...]) -> list[str]:
    rendered = ", ".join(_quoted(value) for value in values)
    inline = f"            {name}=({rendered}{',' if len(values) == 1 else ''}),"
    if len(inline) <= 88:
        return [inline]
    return [
        f"            {name}=(",
        *(f"                {_quoted(value)}," for value in values),
        "            ),",
    ]


def _claim_lines(claim: str) -> list[str]:
    inline = f"            claim={_quoted(claim)},"
    if len(inline) <= 100:
        return [inline]
    parts = textwrap.wrap(
        claim, width=68, break_long_words=True, break_on_hyphens=False
    )
    quoted = [
        _quoted(part + (" " if index < len(parts) - 1 else ""))
        for index, part in enumerate(parts)
    ]
    return [
        "            claim=(",
        *(f"                {part}" for part in quoted),
        "            ),",
    ]


def _mechanism_lines(values: tuple[str, ...]) -> list[str]:
    names = [
        f"DetectionMechanism.{value.upper().replace('-', '_')}" for value in values
    ]
    inline = (
        f"            mechanisms=({', '.join(names)}{',' if len(names) == 1 else ''}),"
    )
    if len(inline) <= 100:
        return [inline]
    return [
        "            mechanisms=(",
        *(f"                {name}," for name in names),
        "            ),",
    ]


def _render_rule_tag(rule_id: str) -> tuple[str, ...]:
    _, scope, framework, category, complaint = rule_id.split("/")
    return (
        "                RuleTag(",
        f"                    Scope.{scope.upper()},",
        f"                    Framework.{framework.upper()},",
        f"                    Category.{category.upper()},",
        f"                    {_quoted(complaint)},",
        "                ),",
    )


def render_manifest(root: Path) -> str:
    """Render the deterministic typed catalog from literal declarations."""
    declarations = _declarations(root)
    lines = [
        '"""Generated by scripts/generate_morphology_manifest.py; do not edit."""',
        "",
        "from collections.abc import Mapping",
        "from types import MappingProxyType",
        "",
        "from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope",
        "from alphus.policy.morphology import (",
        "    ClaimKind,",
        "    DetectionMechanism,",
        "    EvaluationMaturity,",
        "    RuleMorphology,",
        ")",
        "",
        "MORPHOLOGY_BY_SELECTOR: Mapping[str, RuleMorphology] = MappingProxyType(",
        "    {",
    ]
    for item in declarations:
        lines.extend(
            [
                f"        {_quoted(item.selector)}: RuleMorphology(",
                f"            selector={_quoted(item.selector)},",
                "            finding_ids=(",
                *(
                    line
                    for rule_id in item.finding_ids
                    for line in _render_rule_tag(rule_id)
                ),
                "            ),",
                f"            concern={_quoted(item.concern)},",
                f"            claim_kind=ClaimKind.{item.claim_kind.upper().replace('-', '_')},",
                *_claim_lines(item.claim),
                *_mechanism_lines(item.mechanisms),
                *_tuple_lines("inspected_scope", item.inspected_scope),
                *_tuple_lines("languages_formats", item.languages_formats),
                *_tuple_lines("evidence_kinds", item.evidence_kinds),
                (
                    "            evaluation_maturity=EvaluationMaturity."
                    f"{item.evaluation_maturity.upper().replace('-', '_')},"
                ),
                "        ),",
            ]
        )
    lines.extend(["    }", ")", ""])
    return "\n".join(lines)


def render_feature_manifest(root: Path) -> str:
    """Render typed runtime registration data from feature-owned declarations."""
    declarations = [item for item in _declarations(root) if item.feature is not None]
    lines = [
        '"""Generated by scripts/generate_morphology_manifest.py; do not edit."""',
        "",
        "from collections.abc import Mapping",
        "from types import MappingProxyType",
        "",
        "from alphus.policy.feature_definition import FeatureDefinition",
        "",
        "FEATURE_DEFINITIONS: Mapping[str, FeatureDefinition] = MappingProxyType(",
        "    {",
    ]
    for declaration in declarations:
        feature = declaration.feature
        if feature is None:
            continue
        lines.extend(
            [
                f"        {_quoted(feature.selector)}: FeatureDefinition(",
                f"            selector={_quoted(feature.selector)},",
                f"            policy_field={_quoted(feature.policy_field)},",
                f"            policy_model={_quoted(feature.policy_model)},",
                f"            output_shape={_quoted(feature.output_shape)},",
                f"            summary={_quoted(feature.summary)},",
                "            applies_to=("
                + ", ".join(_quoted(value) for value in feature.applies_to)
                + ("," if len(feature.applies_to) == 1 else "")
                + "),",
                "            domains=("
                + ", ".join(_quoted(value) for value in feature.domains)
                + ("," if len(feature.domains) == 1 else "")
                + "),",
                f"            requires_files={feature.requires_files!r},",
                f"            runner_module={_quoted(feature.runner_module)},",
                f"            runner_name={_quoted(feature.runner_name)},",
                "        ),",
            ]
        )
    lines.extend(["    }", ")", ""])
    return "\n".join(lines)


def _policy_class(feature: _FeatureRegistration) -> tuple[str, str]:
    module, class_name = feature.policy_model.rsplit(".", 1)
    return module, class_name


def render_feature_policies(root: Path) -> str:
    """Render strict check-policy fields owned by statically discovered features."""
    declarations = feature_registrations(root)
    fields: dict[str, _FeatureRegistration] = {}
    for feature in declarations:
        if feature.policy_field in fields:
            raise ValueError(f"duplicate feature policy field {feature.policy_field!r}")
        fields[feature.policy_field] = feature
    imports: dict[str, set[str]] = {}
    for feature in fields.values():
        module, class_name = _policy_class(feature)
        imports.setdefault(module, set()).add(class_name)
    lines = [
        '"""Generated by scripts/generate_morphology_manifest.py; do not edit."""',
        "",
        "from __future__ import annotations",
        "",
        "from alphus.policy.base import StrictModel",
    ]
    for module, names in sorted(imports.items()):
        lines.append(f"from {module} import {', '.join(sorted(names))}")
    lines.extend(["", "", "class GeneratedFeaturePolicies(StrictModel):"])
    if not fields:
        lines.append("    pass")
    for policy_field, feature in sorted(fields.items()):
        _, class_name = _policy_class(feature)
        lines.append(f"    {policy_field}: {class_name} | None = None")
    lines.append("")
    return "\n".join(lines)


def render_quality_rule_names(root: Path) -> str:
    """Render the selector type from legacy contracts and feature declarations."""
    catalog_path = root / "src" / "alphus" / "policy" / "catalog.py"
    selectors: set[str] = set()
    if catalog_path.is_file():
        catalog_tree = ast.parse(
            catalog_path.read_text(encoding="utf-8"), filename=str(catalog_path)
        )
        for statement in catalog_tree.body:
            if _assignment_name(statement) != "_LEGACY_RULE_SPECS":
                continue
            value = _assignment_value(statement)
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "MappingProxyType"
            ):
                value = value.args[0] if value.args else value
            if isinstance(value, ast.Dict):
                for key in value.keys:
                    match key:
                        case ast.Constant(value=str(selector)):
                            selectors.add(selector)
                        case _:
                            continue
    if not selectors:
        base_path = root / "src" / "alphus" / "policy" / "base.py"
        if base_path.is_file():
            base_tree = ast.parse(
                base_path.read_text(encoding="utf-8"), filename=str(base_path)
            )
            for statement in base_tree.body:
                if _assignment_name(statement) != "QualityRuleName":
                    continue
                value = _assignment_value(statement)
                if (
                    not isinstance(value, ast.Subscript)
                    or not isinstance(value.value, ast.Name)
                    or value.value.id != "Literal"
                ):
                    continue
                match value.slice:
                    case ast.Tuple(elts=items):
                        candidates: tuple[ast.expr, ...] = tuple(items)
                    case _:
                        candidates = (value.slice,)
                for candidate in candidates:
                    match candidate:
                        case ast.Constant(value=str(selector)):
                            selectors.add(selector)
                        case _:
                            continue
    feature_selectors = {item.selector for item in feature_registrations(root)}
    if selectors.intersection(feature_selectors):
        duplicate = min(selectors.intersection(feature_selectors))
        raise ValueError(f"feature selector duplicates legacy selector {duplicate!r}")
    selectors.update(feature_selectors)
    values = sorted(selectors)
    if not values:
        raise ValueError("no selectors found for QualityRuleName")
    lines = [
        '"""Generated by scripts/generate_morphology_manifest.py; do not edit."""',
        "",
        "from typing import Literal, TypeAlias",
        "",
        "QualityRuleName: TypeAlias = Literal[",
        *(f"    {_quoted(value)}," for value in values),
        "]",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="repository root")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root: Path = args.root
    target = root / _TARGET
    feature_target = root / _FEATURE_TARGET
    feature_policies_target = root / _FEATURE_POLICIES_TARGET
    quality_rules_target = root / _QUALITY_RULES_TARGET
    try:
        expected = render_manifest(root)
        expected_features = render_feature_manifest(root)
        expected_policies = render_feature_policies(root)
        expected_quality_rules = render_quality_rule_names(root)
    except (OSError, SyntaxError, TypeError, ValueError) as error:
        print(f"morphology manifest generation failed: {error}", file=sys.stderr)
        return 1
    if args.check:
        if not target.is_file() or target.read_text(encoding="utf-8") != expected:
            print(
                f"{target} is stale; run scripts/generate_morphology_manifest.py "
                "--root .",
                file=sys.stderr,
            )
            return 1
        if (
            not feature_target.is_file()
            or feature_target.read_text(encoding="utf-8") != expected_features
        ):
            print(
                f"{feature_target} is stale; run "
                "scripts/generate_morphology_manifest.py --root .",
                file=sys.stderr,
            )
            return 1
        if (
            not feature_policies_target.is_file()
            or feature_policies_target.read_text(encoding="utf-8") != expected_policies
        ):
            print(
                f"{feature_policies_target} is stale; regenerate morphology views",
                file=sys.stderr,
            )
            return 1
        if (
            not quality_rules_target.is_file()
            or quality_rules_target.read_text(encoding="utf-8")
            != expected_quality_rules
        ):
            print(
                f"{quality_rules_target} is stale; regenerate morphology views",
                file=sys.stderr,
            )
            return 1
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(expected, encoding="utf-8")
    feature_target.write_text(expected_features, encoding="utf-8")
    feature_policies_target.write_text(expected_policies, encoding="utf-8")
    quality_rules_target.write_text(expected_quality_rules, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
