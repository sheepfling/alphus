"""Lightweight provider contract shared by spike metadata and analyzers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, TypeVar, runtime_checkable

from alphus.contracts.model import StrictModel

SettingsT_contra = TypeVar("SettingsT_contra", bound=StrictModel, contravariant=True)
EvidenceT_co = TypeVar("EvidenceT_co", covariant=True)


@runtime_checkable
class CheckProvider(Protocol[SettingsT_contra, EvidenceT_co]):
    """A provider's typed analysis boundary."""

    def analyze(
        self, root: Path, files: Sequence[Path], settings: SettingsT_contra
    ) -> EvidenceT_co: ...


__all__ = ["CheckProvider"]
