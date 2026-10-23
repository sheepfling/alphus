"""Scan native build artifacts and measure their sections."""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import MappingProxyType

from alphus.gates.cpp.artifact_contracts import (
    ArtifactRow,
    ArtifactScan,
    DebugSignal,
    KindTotals,
    SectionInventory,
    SectionMetrics,
)
from alphus.support.native_artifacts import artifact_kind, is_unix_executable

DEFAULT_INCLUDE_GLOBS = (
    "*.exe",
    "*.dll",
    "*.so",
    "*.so.*",
    "*.dylib",
    "*.a",
    "*.lib",
    "*.pdb",
    "*.debug",
    "*.dwp",
    "*.dSYM/Contents/Resources/DWARF/*",
)
SECTION_HEADER_REGEX = re.compile(r"^\s*\d+\s+(\S+)\s+([0-9a-fA-F]+)\s+", re.MULTILINE)
DEBUG_DOMINANCE_MIN_BYTES = 64 * 1024 * 1024
MAX_REVIEW_EXAMPLES = 8


def _matches(path: str, patterns: Sequence[str]) -> bool:
    """Match normalized relative paths against case-insensitive glob patterns."""
    folded = path.casefold()
    return any(fnmatch.fnmatchcase(folded, pattern.casefold()) for pattern in patterns)


def parse_objdump_sections(output: str) -> SectionInventory:
    """Return section sizes in bytes from GNU/LLVM objdump -h output."""
    sections: dict[str, int] = {}
    for name, hexadecimal_size in SECTION_HEADER_REGEX.findall(output):
        sections[name] = sections.get(name, 0) + int(hexadecimal_size, 16)
    if not sections:
        raise ValueError("objdump returned no section headers")
    return SectionInventory(MappingProxyType(sections))


def _section_metrics(path: Path, section_tool: str | None) -> SectionMetrics:
    if section_tool is None:
        return SectionMetrics("unavailable", error="objdump was not found")
    try:
        result = subprocess.run(
            [section_tool, "-h", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise ValueError(result.stderr.strip()[:240] or "objdump failed")
        sections = parse_objdump_sections(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return SectionMetrics("error", error=str(error)[:240])
    return SectionMetrics("measured", sections.debug_bytes, sections.text_bytes)


def scan_directory(
    root: Path,
    *,
    includes: Sequence[str] = DEFAULT_INCLUDE_GLOBS,
    excludes: Sequence[str] = (),
    section_tool: str = "objdump",
    measure_sections: bool = True,
    include_unix_executables: bool = True,
) -> ArtifactScan:
    """Scan a directory; includes and excludes are glob patterns, not regexes."""
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"artifact root is not a directory: {root}")
    includes = tuple(includes)
    excludes = tuple(excludes)
    if not includes:
        raise ValueError("at least one include pattern is required")
    analyzer = shutil.which(section_tool) if measure_sections else None
    artifacts: list[ArtifactRow] = []
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if (
            not _matches(relative, includes)
            and not (include_unix_executables and is_unix_executable(path))
        ) or _matches(relative, excludes):
            continue
        kind = artifact_kind(path)
        item: ArtifactRow = {
            "path": relative,
            "kind": kind,
            "bytes": path.stat().st_size,
        }
        if kind in {"executable", "shared_library"}:
            metrics = (
                _section_metrics(path, analyzer)
                if measure_sections
                else SectionMetrics("skipped")
            )
            item["section_status"] = metrics.status
            item["debug_bytes"] = metrics.debug_bytes
            item["text_bytes"] = metrics.text_bytes
            if metrics.error is not None:
                item["section_error"] = metrics.error
        artifacts.append(item)
    artifacts.sort(key=lambda item: item["path"])
    executables = [item for item in artifacts if item["kind"] == "executable"]
    static_libraries = [item for item in artifacts if item["kind"] == "static_library"]
    by_kind: dict[str, KindTotals] = {}
    for item in artifacts:
        bucket = by_kind.setdefault(item["kind"], {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += item["bytes"]
    debug_dominant = [
        item
        for item in executables
        if "debug_bytes" in item
        and item["debug_bytes"] is not None
        and item["debug_bytes"] >= DEBUG_DOMINANCE_MIN_BYTES
        and item["debug_bytes"] * 2 >= item["bytes"]
    ]
    debug_dominant.sort(key=lambda item: item["debug_bytes"] or 0, reverse=True)
    signals: list[DebugSignal] = []
    if debug_dominant:
        signals.append(
            {
                "code": "debug_dominant_executables",
                "count": len(debug_dominant),
                "total_debug_bytes": sum(
                    item["debug_bytes"] or 0 for item in debug_dominant
                ),
                "examples": [
                    item["path"] for item in debug_dominant[:MAX_REVIEW_EXAMPLES]
                ],
            }
        )
    return {
        "schema": 1,
        "root": str(root),
        "include": list(includes),
        "exclude": list(excludes),
        "include_unix_executables": include_unix_executables,
        "section_tool": analyzer,
        "artifacts": artifacts,
        "totals": {
            "count": len(artifacts),
            "bytes": sum(item["bytes"] for item in artifacts),
            "executable_count": len(executables),
            "executable_paths": sorted(item["path"] for item in executables),
            "executable_bytes": sum(item["bytes"] for item in executables),
            "static_library_count": len(static_libraries),
            "static_library_bytes": sum(item["bytes"] for item in static_libraries),
            "measured_debug_bytes": sum(
                item["debug_bytes"] or 0
                for item in artifacts
                if "debug_bytes" in item and item["debug_bytes"] is not None
            ),
            "section_measured_count": sum(
                item.get("section_status") == "measured" for item in artifacts
            ),
            "section_unmeasured_count": sum(
                item.get("section_status") in {"skipped", "unavailable", "error"}
                for item in artifacts
            ),
            "by_kind": by_kind,
        },
        "review_signals": signals,
    }
