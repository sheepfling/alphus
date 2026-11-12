"""Typed compatibility exports resolved lazily by the package implementation."""

from collections.abc import Iterable, Sequence
from pathlib import Path

from alphus.config import (
    PathDiscoveryPolicy as PathDiscoveryPolicy,
)
from alphus.config import (
    QualityGateConfig as QualityGateConfig,
)
from alphus.config import (
    SourceScanPolicy as SourceScanPolicy,
)
from alphus.config import (
    load_config as load_config,
)
from alphus.contracts.findings import Finding as Finding
from alphus.support.inventory import (
    candidate_files as candidate_files,
)
from alphus.support.inventory import (
    git_files as git_files,
)

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

def check_file_size(
    root: Path, files: Sequence[Path], config: QualityGateConfig
) -> list[Finding]: ...
def check_line_length(
    root: Path, files: Sequence[Path], config: QualityGateConfig
) -> list[Finding]: ...
def check_json_structure(
    root: Path, files: Iterable[Path], policy: SourceScanPolicy
) -> list[Finding]: ...
def check_path_discovery(
    root: Path, files: Iterable[Path], policy: PathDiscoveryPolicy
) -> list[Finding]: ...
def check_output_escaping(
    root: Path, files: Iterable[Path], policy: SourceScanPolicy
) -> list[Finding]: ...
