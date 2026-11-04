"""Generate the static morphology catalog from feature-owned literal declarations.

The generator parses first-party source with ``ast`` and ``ast.literal_eval``. It
never imports check modules or executes repository code.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_DECLARATION_NAME = "ALPHUS_MORPHOLOGY"
_DECLARATION_FIELDS = frozenset(
    {
        "selector",
        "finding_ids",
        "concern",
        "claim",
        "mechanisms",
        "inspected_scope",
        "languages_formats",
        "evidence_kinds",
        "evaluation_maturity",
    }
)
_MECHANISMS = frozenset(
    {
        "exact-rule",
        "bounded-heuristic",
        "prose-risk",
        "style-preference",
        "native-tool",
        "local-model-assisted",
    }
)
_MATURITY = frozenset(
    {"unassessed", "synthetic-only", "public-sample-reviewed", "human-evaluated"}
)
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_TARGET = Path("src/alphus/policy/_generated_morphology.py")
_MAX_FEATURE_MODULES = 2048
_MAX_SOURCE_MODULE_BYTES = 1_048_576
_MAX_SCANNED_SOURCE_BYTES = 16_777_216


@dataclass(frozen=True, slots=True)
class _Declaration:
    selector: str
    finding_ids: tuple[str, ...]
    concern: str
    claim: str
    mechanisms: tuple[str, ...]
    inspected_scope: tuple[str, ...]
    languages_formats: tuple[str, ...]
    evidence_kinds: tuple[str, ...]
    evaluation_maturity: str
    source: str


def _assignment_name(statement: ast.stmt) -> str | None:
    if isinstance(statement, ast.AnnAssign):
        target = statement.target
    elif isinstance(statement, ast.Assign) and statement.targets:
        target = statement.targets[0]
    else:
        return None
    return target.id if isinstance(target, ast.Name) else None


def _assignment_value(statement: ast.stmt) -> ast.expr | None:
    if isinstance(statement, (ast.AnnAssign, ast.Assign)):
        return statement.value
    return None


def _catalog_selectors(root: Path) -> frozenset[str]:
    path = root / "src" / "alphus" / "policy" / "catalog.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        if _assignment_name(statement) != "_LEGACY_RULE_SPECS":
            continue
        value = _assignment_value(statement)
        if (
            not isinstance(value, ast.Call)
            or not isinstance(value.func, ast.Name)
            or value.func.id != "MappingProxyType"
            or value.keywords
            or len(value.args) != 1
            or not isinstance(value.args[0], ast.Dict)
        ):
            raise ValueError("RULE_SPECS must be a MappingProxyType literal")
        selectors: set[str] = set()
        for key in value.args[0].keys:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                raise TypeError("RULE_SPECS must use literal string selectors")
            selectors.add(key.value)
        return frozenset(selectors)
    raise ValueError(f"{path} must define _LEGACY_RULE_SPECS")


def _static_rule_ids(tree: ast.Module) -> frozenset[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "rule_tag" or len(node.args) != 4 or node.keywords:
            continue
        scope, framework, category, complaint = node.args
        if (
            not isinstance(scope, ast.Attribute)
            or not isinstance(scope.value, ast.Name)
            or not isinstance(framework, ast.Attribute)
            or not isinstance(framework.value, ast.Name)
            or not isinstance(category, ast.Attribute)
            or not isinstance(category.value, ast.Name)
            or not isinstance(complaint, ast.Constant)
            or not isinstance(complaint.value, str)
        ):
            continue
        result.add(
            f"alphus/{scope.attr.lower()}/{framework.attr.lower()}"
            f"/{category.attr.lower()}/{complaint.value}"
        )
    return frozenset(result)


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or not value:
        raise ValueError(f"{field} must be a non-empty tuple of strings")
    result: list[str] = []
    items = cast(tuple[object, ...] | list[object], value)
    for item in items:
        if not isinstance(item, str):
            raise TypeError(f"{field} must contain only strings")
        result.append(item)
    values = tuple(result)
    if len(values) != len(set(values)):
        raise ValueError(f"{field} must not contain duplicates")
    return values


def _validate_declaration(value: object, path: Path) -> _Declaration:
    if not isinstance(value, dict):
        raise TypeError(f"{path}:{_DECLARATION_NAME} must be a literal mapping")
    declaration: dict[str, object] = {}
    entries = cast(dict[object, object], value)
    for key, item in entries.items():
        if not isinstance(key, str):
            raise TypeError(f"{path}:{_DECLARATION_NAME} keys must be strings")
        declaration[key] = item
    if declaration.keys() != _DECLARATION_FIELDS:
        raise ValueError(
            f"{path}:{_DECLARATION_NAME} must contain exactly "
            f"{sorted(_DECLARATION_FIELDS)}"
        )

    selector = declaration["selector"]
    concern = declaration["concern"]
    claim = declaration["claim"]
    if not isinstance(selector, str) or not _SLUG.fullmatch(selector):
        raise ValueError(f"{path}: selector must be a lowercase slug")
    if not isinstance(concern, str) or not _SLUG.fullmatch(concern):
        raise ValueError(f"{path}: concern must be a lowercase slug")
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError(f"{path}: claim must be non-empty text")

    finding_ids = _string_tuple(declaration["finding_ids"], "finding_ids")
    inspected_scope = _string_tuple(declaration["inspected_scope"], "inspected_scope")
    languages_formats = _string_tuple(
        declaration["languages_formats"], "languages_formats"
    )
    evidence_kinds = _string_tuple(declaration["evidence_kinds"], "evidence_kinds")
    for finding_id in finding_ids:
        parts = finding_id.split("/")
        if len(parts) != 5 or parts[0] != "alphus":
            raise ValueError(f"{path}: invalid Alphus finding ID {finding_id!r}")
        if any(not _SLUG.fullmatch(part) for part in parts[1:]):
            raise ValueError(f"{path}: invalid Alphus finding ID {finding_id!r}")

    mechanisms = _string_tuple(declaration["mechanisms"], "mechanisms")
    if not set(mechanisms) <= _MECHANISMS:
        raise ValueError(f"{path}: unsupported morphology mechanism")
    maturity = declaration["evaluation_maturity"]
    if not isinstance(maturity, str) or maturity not in _MATURITY:
        raise ValueError(f"{path}: unsupported evaluation_maturity {maturity!r}")
    return _Declaration(
        selector=selector,
        finding_ids=finding_ids,
        concern=concern,
        claim=claim,
        mechanisms=mechanisms,
        inspected_scope=inspected_scope,
        languages_formats=languages_formats,
        evidence_kinds=evidence_kinds,
        evaluation_maturity=maturity,
        source=path.as_posix(),
    )


def _declarations(root: Path) -> tuple[_Declaration, ...]:
    gates = root / "src" / "alphus" / "gates"
    selectors = _catalog_selectors(root)
    declarations: list[_Declaration] = []
    paths: list[Path] = []
    for path in gates.rglob("*.py"):
        paths.append(path)
        if len(paths) > _MAX_FEATURE_MODULES:
            raise ValueError(
                f"feature discovery exceeds {_MAX_FEATURE_MODULES} Python modules"
            )
    paths.sort()

    scanned_bytes = 0
    for path in paths:
        source_bytes = path.stat().st_size
        if source_bytes > _MAX_SOURCE_MODULE_BYTES:
            raise ValueError(
                f"{path} exceeds the {_MAX_SOURCE_MODULE_BYTES}-byte scan limit"
            )
        scanned_bytes += source_bytes
        if scanned_bytes > _MAX_SCANNED_SOURCE_BYTES:
            raise ValueError(
                f"feature discovery exceeds the {_MAX_SCANNED_SOURCE_BYTES}-byte scan limit"
            )

    actual_scanned_bytes = 0
    for path in paths:
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
        if _DECLARATION_NAME not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        values: list[ast.expr] = []
        for statement in tree.body:
            if _assignment_name(statement) == _DECLARATION_NAME:
                value = _assignment_value(statement)
                if value is None:
                    raise ValueError(f"{path} must assign {_DECLARATION_NAME}")
                values.append(value)
        if len(values) != 1:
            raise ValueError(f"{path} must define exactly one {_DECLARATION_NAME}")
        try:
            raw: object = ast.literal_eval(values[0])
        except (ValueError, TypeError, SyntaxError) as error:
            raise ValueError(f"{path}:{_DECLARATION_NAME} must be a literal") from error
        if isinstance(raw, (tuple, list)):
            records = cast(tuple[object, ...] | list[object], raw)
        else:
            records = (raw,)
        for item in records:
            declaration = _validate_declaration(item, path)
            if declaration.selector not in selectors:
                raise ValueError(
                    f"{path}: unknown built-in selector {declaration.selector!r}"
                )
            missing_ids = set(declaration.finding_ids) - _static_rule_ids(tree)
            if missing_ids:
                raise ValueError(
                    f"{path}: finding IDs are not declared by this feature: "
                    f"{sorted(missing_ids)}"
                )
            declarations.append(declaration)

    owners: dict[str, str] = {}
    for declaration in declarations:
        if declaration.selector in owners:
            raise ValueError(
                f"duplicate morphology selector {declaration.selector!r} in "
                f"{owners[declaration.selector]} and {declaration.source}"
            )
        owners[declaration.selector] = declaration.source
    if not declarations:
        raise ValueError(f"no {_DECLARATION_NAME} declarations found under {gates}")
    return tuple(sorted(declarations, key=lambda item: item.selector))


def _tuple(values: tuple[str, ...]) -> str:
    return repr(values)


def render_manifest(root: Path) -> str:
    """Render the deterministic typed catalog from literal declarations."""
    declarations = _declarations(root)
    lines = [
        '"""Generated by scripts/generate_morphology_manifest.py; do not edit."""',
        "",
        "from collections.abc import Mapping",
        "from types import MappingProxyType",
        "",
        "from alphus.policy.morphology import (",
        "    DetectionMechanism,",
        "    EvaluationMaturity,",
        "    RuleMorphology,",
        ")",
        "",
        "MORPHOLOGY_BY_SELECTOR: Mapping[str, RuleMorphology] = MappingProxyType(",
        "    {",
    ]
    for item in declarations:
        mechanisms = ", ".join(
            f"DetectionMechanism.{value.upper().replace('-', '_')}"
            for value in item.mechanisms
        )
        lines.extend(
            [
                f"        {item.selector!r}: RuleMorphology(",
                f"            selector={item.selector!r},",
                f"            finding_ids={_tuple(item.finding_ids)},",
                f"            concern={item.concern!r},",
                f"            claim={item.claim!r},",
                f"            mechanisms=({mechanisms},),",
                f"            inspected_scope={_tuple(item.inspected_scope)},",
                f"            languages_formats={_tuple(item.languages_formats)},",
                f"            evidence_kinds={_tuple(item.evidence_kinds)},",
                (
                    "            evaluation_maturity=EvaluationMaturity."
                    f"{item.evaluation_maturity.upper().replace('-', '_')},"
                ),
                "        ),",
            ]
        )
    lines.extend(["    }", ")", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="repository root")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root: Path = args.root
    target = root / _TARGET
    try:
        expected = render_manifest(root)
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
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
