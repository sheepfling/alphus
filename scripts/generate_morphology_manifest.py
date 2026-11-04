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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_DECLARATION_NAME = "ALPHUS_MORPHOLOGY"
_DECLARATION_FIELDS = frozenset(
    {
        "selector",
        "finding_tag_complaints",
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
_MAX_FEATURE_MODULES = 2048
_MAX_SOURCE_MODULE_BYTES = 1_048_576
_MAX_SCANNED_SOURCE_BYTES = 16_777_216


@dataclass(frozen=True, slots=True)
class _Declaration:
    selector: str
    finding_ids: tuple[str, ...]
    concern: str
    claim_kind: str
    claim: str
    mechanisms: tuple[str, ...]
    inspected_scope: tuple[str, ...]
    languages_formats: tuple[str, ...]
    evidence_kinds: tuple[str, ...]
    evaluation_maturity: str
    source: str


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


def _static_rule_ids(tree: ast.Module) -> frozenset[str]:
    result: set[str] = set()
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
                result.add(
                    f"alphus/{scope.lower()}/{framework.lower()}/{category.lower()}"
                    f"/{complaint}"
                )
            case _:
                pass
    return frozenset(result)


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


def _validate_declaration(value: object, path: Path) -> _Declaration:
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
    if len(keys) != len(pairs) or keys != _DECLARATION_FIELDS:
        raise ValueError(
            f"{path}:{_DECLARATION_NAME} must contain exactly "
            f"{sorted(_DECLARATION_FIELDS)} with unique keys"
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

    complaints = _string_tuple(
        field("finding_tag_complaints"), "finding_tag_complaints"
    )
    for complaint in complaints:
        if not _SLUG.fullmatch(complaint):
            raise ValueError(f"{path}: invalid finding complaint {complaint!r}")
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
    return _Declaration(
        selector=selector_text,
        finding_ids=complaints,
        concern=concern_text,
        claim_kind=claim_kind_text,
        claim=claim_text,
        mechanisms=mechanisms,
        inspected_scope=inspected_scope,
        languages_formats=languages_formats,
        evidence_kinds=evidence_kinds,
        evaluation_maturity=maturity_text,
        source=path.as_posix(),
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


def _declarations(root: Path) -> tuple[_Declaration, ...]:
    gates = root / "src" / "alphus" / "gates"
    gates_root = gates.resolve(strict=True)
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
        records = _declaration_records(raw)
        for item in records:
            declaration = _validate_declaration(item, path)
            local_ids = _static_rule_ids(tree)
            resolved_ids = tuple(
                rule_id
                for complaint in declaration.finding_ids
                for rule_id in local_ids
                if rule_id.rsplit("/", 1)[-1] == complaint
            )
            if len(resolved_ids) != len(declaration.finding_ids):
                missing = set(declaration.finding_ids) - {
                    rule_id.rsplit("/", 1)[-1] for rule_id in local_ids
                }
                raise ValueError(
                    f"{path}: finding complaints are not declared by this feature: "
                    f"{sorted(missing)}"
                )
            declarations.append(
                _Declaration(
                    selector=declaration.selector,
                    finding_ids=resolved_ids,
                    concern=declaration.concern,
                    claim_kind=declaration.claim_kind,
                    claim=declaration.claim,
                    mechanisms=declaration.mechanisms,
                    inspected_scope=declaration.inspected_scope,
                    languages_formats=declaration.languages_formats,
                    evidence_kinds=declaration.evidence_kinds,
                    evaluation_maturity=declaration.evaluation_maturity,
                    source=declaration.source,
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
        for finding_id in declaration.finding_ids:
            owner = finding_owners.get(finding_id)
            if owner is not None and owner != declaration.selector:
                raise ValueError(
                    f"finding ID {finding_id!r} is declared by multiple selectors: "
                    f"{owner!r} and {declaration.selector!r}"
                )
            finding_owners[finding_id] = declaration.selector
    if not declarations:
        raise ValueError(f"no {_DECLARATION_NAME} declarations found under {gates}")
    return tuple(sorted(declarations, key=lambda item: item.selector))


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


def main(argv: Sequence[str] | None = None) -> int:
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
