"""Portable repository quality gates driven by validated TOML policy."""

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from alphus.config import (
    PathDiscoveryPolicy,
    QualityGateConfig,
    SourceScanPolicy,
    load_config,
)
from alphus.contracts.findings import Finding
from alphus.support.inventory import candidate_files, git_files
from alphus.support.public_imports import make_public_dir, resolve_public_attribute

check_file_size: Callable[[Path, Sequence[Path], QualityGateConfig], list[Finding]]
check_line_length: Callable[[Path, Sequence[Path], QualityGateConfig], list[Finding]]
check_json_structure: Callable[[Path, Iterable[Path], SourceScanPolicy], list[Finding]]
check_path_discovery: Callable[
    [Path, Iterable[Path], PathDiscoveryPolicy], list[Finding]
]
check_output_escaping: Callable[[Path, Iterable[Path], SourceScanPolicy], list[Finding]]


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
