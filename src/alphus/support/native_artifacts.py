"""Recognize native binary artifacts independently of build systems."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from alphus.support.platform_utils import is_windows


class ArtifactKind(StrEnum):
    EXECUTABLE = "executable"
    SHARED_LIBRARY = "shared_library"
    STATIC_LIBRARY = "static_library"
    SYMBOLS = "symbols"
    OTHER = "other"


def artifact_kind(path: Path) -> ArtifactKind:
    name = path.name.casefold()
    if ".dsym/contents/resources/dwarf/" in path.as_posix().casefold():
        return ArtifactKind.SYMBOLS
    if name.endswith(".exe"):
        return ArtifactKind.EXECUTABLE
    if name.endswith((".dll", ".dylib", ".so")) or ".so." in name:
        return ArtifactKind.SHARED_LIBRARY
    if name.endswith((".a", ".lib")):
        return ArtifactKind.STATIC_LIBRARY
    if name.endswith((".pdb", ".debug", ".dwp")):
        return ArtifactKind.SYMBOLS
    with path.open("rb") as binary:
        magic = binary.read(4)
    if (
        magic.startswith(b"MZ")
        or magic == b"\x7fELF"
        or magic
        in {
            b"\xfe\xed\xfa\xce",
            b"\xce\xfa\xed\xfe",
            b"\xfe\xed\xfa\xcf",
            b"\xcf\xfa\xed\xfe",
        }
    ):
        return ArtifactKind.EXECUTABLE
    return ArtifactKind.OTHER


def is_unix_executable(path: Path) -> bool:
    """Include extensionless native executables on Unix without reading all files."""
    return (
        not is_windows()
        and os.access(path, os.X_OK)
        and artifact_kind(path) == ArtifactKind.EXECUTABLE
    )
