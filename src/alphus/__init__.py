"""Portable repository quality gates driven by validated TOML policy."""

from __future__ import annotations

from alphus.support.public_imports import make_public_dir, resolve_public_attribute

Finding: type[object]
QualityGateConfig: type[object]
candidate_files: object
check_file_size: object
check_json_structure: object
check_line_length: object
check_output_escaping: object
check_path_discovery: object
git_files: object
load_config: object

__all__ = [
    "Finding",
    "QualityGateConfig",
    "candidate_files",
    "check_file_size",
    "check_json_structure",
    "check_line_length",
    "check_output_escaping",
    "check_path_discovery",
    "git_files",
    "load_config",
]

__getattr__ = resolve_public_attribute
__dir__ = make_public_dir(tuple(globals()), __all__)
