"""Python checks for hand-written output escaping."""

from __future__ import annotations

import ast
import re

_OUTPUT_PUNCTUATION = frozenset("\\|*_<>&\"'{}[]#%$~^/")
_HTML_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]+|#[0-9]+|#x[0-9A-Fa-f]+);")


def _literal_text(node: ast.expr) -> str | None:
    """Read a literal string without evaluating source code."""
    match node:
        case ast.Constant(value=str() as value):
            return value
        case _:
            return None


def _is_manual_escape(source: str, replacement: str) -> bool:
    """Recognize format punctuation mapped to an escape sequence or entity."""
    if not source or not set(source) <= _OUTPUT_PUNCTUATION:
        return source in {"\n", "\r", "\t"} and replacement in {
            "\\n",
            "\\r",
            "\\t",
        }
    return (
        bool(replacement)
        and replacement[0] == "\\"
        or _HTML_ENTITY.fullmatch(replacement) is not None
    )


def escape_findings(source: str) -> list[tuple[int, str]]:
    """Find Python literal replacement calls and character escape tables."""
    findings: set[tuple[int, str]] = set()
    for node in ast.walk(ast.parse(source)):
        match node:
            case ast.Call(func=ast.Attribute(attr=attribute), args=arguments) if (
                attribute in {"replace", "replaceAll"} and len(arguments) >= 2
            ):
                original = _literal_text(arguments[0])
                replacement = _literal_text(arguments[1])
                if (
                    original is not None
                    and replacement is not None
                    and _is_manual_escape(original, replacement)
                ):
                    findings.add((node.lineno, "manual output escape replacement"))
            case ast.Dict(keys=keys, values=values):
                for key, value in zip(keys, values):
                    if key is None:
                        continue
                    original = _literal_text(key)
                    replacement = _literal_text(value)
                    if (
                        original is not None
                        and replacement is not None
                        and _is_manual_escape(original, replacement)
                    ):
                        findings.add((node.lineno, "manual output escape table"))
                        break
            case _:
                pass
    return sorted(findings)
