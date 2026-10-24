"""Load one explicitly configured consumer FastAPI application."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

from alphus.config import FastApiPracticePolicy


class FastApiContractError(RuntimeError):
    """A configured application could not be imported or inspected safely."""


def _application_import_paths(root: Path, paths: tuple[str, ...]) -> list[str]:
    resolved_paths: list[str] = []
    for name in paths:
        resolved = (root / name).resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise FastApiContractError(
                f"application Python path escapes the repository: {name}"
            ) from error
        if not resolved.is_dir():
            raise FastApiContractError(
                f"application Python path is not a directory: {name}"
            )
        resolved_paths.append(os.fspath(resolved))
    return resolved_paths


def load_application(
    root: Path, policy: FastApiPracticePolicy, fastapi_type: type[object]
) -> object:
    """Import only the configured app and call a factory only by opt-in."""
    target = policy.application
    if target is None:
        raise FastApiContractError(
            "FastAPI application review has no configured application"
        )
    module_name, _, attribute_path = target.partition(":")
    original_path = sys.path.copy()
    try:
        extra_paths = _application_import_paths(root, policy.application_python_paths)
        sys.path[:0] = [*extra_paths, os.fspath(root)]
        try:
            value: Any = importlib.import_module(module_name)
            for name in attribute_path.split("."):
                value = getattr(value, name)
        except (ImportError, AttributeError) as error:
            raise FastApiContractError(
                f"could not load configured FastAPI application {target!r} "
                f"({type(error).__name__})"
            ) from error
    finally:
        sys.path[:] = original_path
    if policy.application_factory:
        if not callable(value):
            raise FastApiContractError(
                f"configured FastAPI application factory {target!r} is not callable"
            )
        try:
            value = value()
        except Exception as error:
            raise FastApiContractError(
                f"configured FastAPI application factory {target!r} failed "
                f"({type(error).__name__})"
            ) from error
    if not issubclass(type(value), fastapi_type):
        raise FastApiContractError(
            f"configured application {target!r} is not a FastAPI instance"
        )
    return value
