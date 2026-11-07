"""Resolve selected compatibility exports without loading every checker."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from importlib import import_module


def resolve_public_attribute(name: str) -> object:
    """Resolve a legacy root-package checker export on explicit access."""
    if name == "check_file_size":
        return import_module("alphus.gates.hygiene.file_size").check_file_size
    if name == "check_line_length":
        return import_module("alphus.gates.hygiene.line_length").check_line_length
    if name == "check_json_structure":
        return import_module("alphus.gates.source.json_structure").check_json_structure
    if name == "check_path_discovery":
        return import_module("alphus.gates.source.path_discovery").check_path_discovery
    if name == "check_output_escaping":
        return import_module(
            "alphus.gates.source.output_escaping"
        ).check_output_escaping
    raise AttributeError(f"module 'alphus' has no attribute {name!r}")


def make_public_dir(
    module_names: Sequence[str], public_names: Sequence[str]
) -> Callable[[], list[str]]:
    """Build module introspection that includes lazy public exports."""
    initial_names = tuple(module_names)
    exported_names = tuple(public_names)

    def public_names_for_module() -> list[str]:
        return sorted(set(initial_names) | set(exported_names))

    return public_names_for_module
