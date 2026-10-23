"""Compatibility imports for the path-discovery source gate."""

from alphus.gates.source.path_discovery import (
    JS_INSPECTION_PATTERNS,
    JS_PATTERNS,
    SYS_PATH_MUTATORS,
    check_path_discovery,
    has_source_file_reference,
    js_inspection_findings,
    js_path_findings,
    python_inspection_findings,
    python_path_findings,
)

__all__ = [
    "JS_INSPECTION_PATTERNS",
    "JS_PATTERNS",
    "SYS_PATH_MUTATORS",
    "check_path_discovery",
    "has_source_file_reference",
    "js_inspection_findings",
    "js_path_findings",
    "python_inspection_findings",
    "python_path_findings",
]
