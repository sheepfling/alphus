"""Python checks for unvalidated JSON decoder results."""

from __future__ import annotations

import ast

from alphus.findings import SourceFinding

DECODER_MODULES: frozenset[str] = frozenset({"json", "orjson", "ujson", "rapidjson"})


def json_findings(source: str) -> list[SourceFinding]:
    """Locate standard and alternate Python JSON decoder calls."""
    tree = ast.parse(source)
    modules: set[str] = set()
    functions: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=names):
                modules.update(
                    alias.asname or alias.name
                    for alias in names
                    if alias.name in DECODER_MODULES
                )
            case ast.ImportFrom(module=module, names=names) if (
                module in DECODER_MODULES
            ):
                for alias in names:
                    if alias.name in {"load", "loads"}:
                        functions.add(alias.asname or alias.name)
            case _:
                pass
    findings: set[SourceFinding] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Call(func=ast.Name(id=name)) if name in functions:
                findings.add(
                    SourceFinding(
                        node.lineno, "raw JSON decode; validate into a named model"
                    )
                )
            case ast.Call(func=ast.Attribute(attr=attr, value=ast.Name(id=name))) if (
                attr in {"load", "loads"} and name in modules
            ):
                findings.add(
                    SourceFinding(
                        node.lineno, "raw JSON decode; validate into a named model"
                    )
                )
            case _:
                pass
    return sorted(findings)
