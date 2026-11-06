"""Resolve selected compatibility exports without loading every checker."""

from __future__ import annotations

from importlib import import_module


def resolve_public_attribute(name: str) -> object:
    """Resolve a legacy root-package checker export on explicit access."""
    if name == "check_file_size":
        return import_module("alphus.gates.hygiene.file_size").check_file_size
    if name == "check_line_length":
        return import_module("alphus.gates.hygiene.line_length").check_line_length
    if name == "check_output_escaping":
        return import_module(
            "alphus.gates.source.output_escaping"
        ).check_output_escaping
    raise AttributeError(f"module 'alphus' has no attribute {name!r}")
