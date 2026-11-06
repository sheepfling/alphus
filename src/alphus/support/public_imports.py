"""Resolve selected compatibility exports without loading every checker."""

from __future__ import annotations

from importlib import import_module


def resolve_public_attribute(name: str) -> object:
    """Resolve a legacy root-package checker export on explicit access."""
    if name == "check_file_size":
        return import_module("alphus.gates.hygiene.file_size").check_file_size
    raise AttributeError(f"module 'alphus' has no attribute {name!r}")
