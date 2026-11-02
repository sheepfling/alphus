"""Opt-in, content-addressed cache for the file-local output-escaping check."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from alphus.config import SourceScanPolicy
from alphus.contracts.findings import Finding, FindingWire
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.gates.source.output_escaping import output_escaping_findings_for_source
from alphus.support.data_access import JsonValue
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_utf8_text

_CACHE_FORMAT = "alphus.local-rule-cache"
_CACHE_SCHEMA_VERSION = 1
# Bump when output-escaping semantics change. Content and policy hashes alone
# cannot invalidate results produced by a different implementation.
_OUTPUT_ESCAPING_RULE_VERSION = 1
_MAX_CACHE_BYTES = 32 * 1024 * 1024


class _CacheEntryWire(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    content_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    findings: list[FindingWire]


class _CachePayloadWire(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    header: dict[str, str | int]
    entries: dict[str, _CacheEntryWire]


@dataclass(frozen=True, slots=True)
class OutputEscapingCacheSummary:
    """Counters for one direct output-escaping scan."""

    hits: int
    misses: int
    pruned: int
    invalidation: str | None
    force_fresh: bool
    saved: bool

    def describe(self) -> str:
        """Return a concise, human-readable cache status."""
        status = f"{self.hits} hit(s), {self.misses} miss(es), {self.pruned} stale path(s) pruned"
        if self.force_fresh:
            status += "; forced fresh"
        if self.invalidation:
            status += f"; prior cache invalidated: {self.invalidation}"
        if not self.saved:
            status += "; cache not saved (scan results are fresh)"
        return status


def _pairs_without_duplicates(
    pairs: Iterable[tuple[str, JsonValue]],
) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key in local cache")
        result[key] = value
    return result


def _fingerprint(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_payload(cache_path: Path) -> JsonValue:
    decoder = json.JSONDecoder(object_pairs_hook=_pairs_without_duplicates)
    return cast(JsonValue, decoder.decode(read_utf8_text(cache_path)))


def _cache_header(root: Path, policy: SourceScanPolicy) -> dict[str, JsonValue]:
    configuration = json.dumps(
        policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    root_identity = os.fsencode(root.resolve(strict=True))
    return {
        "format": _CACHE_FORMAT,
        "schema_version": _CACHE_SCHEMA_VERSION,
        "rule": "output-escaping",
        "rule_version": _OUTPUT_ESCAPING_RULE_VERSION,
        "root_sha256": _fingerprint(root_identity),
        "policy_sha256": _fingerprint(configuration),
    }


def _load_entries(
    cache_path: Path, expected_header: Mapping[str, JsonValue]
) -> tuple[dict[str, JsonValue], str | None]:
    try:
        if cache_path.stat().st_size > _MAX_CACHE_BYTES:
            return {}, "cache exceeds the size limit"
        payload = _read_payload(cache_path)
    except FileNotFoundError:
        return {}, None
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return {}, "cache is unreadable or invalid"

    return _validate_payload(payload, expected_header)


def _validate_payload(
    payload: JsonValue, expected_header: Mapping[str, JsonValue]
) -> tuple[dict[str, JsonValue], str | None]:
    try:
        parsed = _CachePayloadWire.model_validate(payload, strict=True)
    except (ValidationError, TypeError):
        return {}, "cache schema or entries are invalid"
    if parsed.header != dict(expected_header):
        return {}, "root, policy, schema, or rule version changed"
    return (
        {path: entry.model_dump(mode="json") for path, entry in parsed.entries.items()},
        None,
    )


def _finding_rows(
    path: str, rows: Iterable[FindingWire], extension: str
) -> list[Finding]:
    expected_rule_id = rule_tag(
        Scope.PYTHON if extension == ".py" else Scope.JAVASCRIPT,
        Framework.NONE,
        Category.SECURITY,
        "manual-output-escaping",
    )
    findings: list[Finding] = []
    for row in rows:
        wire = row
        if wire.path != path or wire.rule_id != expected_rule_id:
            raise ValueError("cached finding identity does not match its source path")
        findings.append(
            Finding(
                rule_id=wire.rule_id,
                path=wire.path,
                message=wire.message,
                line=wire.line,
                severity=wire.severity,
            )
        )
    return findings


def _read_source(raw: bytes) -> str:
    """Match ``Path.read_text(encoding='utf-8-sig')`` newline behavior."""
    with io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig") as stream:
        return stream.read()


def _write_cache(
    cache_path: Path,
    header: Mapping[str, JsonValue],
    entries: Mapping[str, JsonValue],
) -> bool:
    temporary: str | None = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{cache_path.name}.", suffix=".tmp", dir=cache_path.parent
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                {"header": dict(header), "entries": dict(entries)},
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, cache_path)
        return True
    except (OSError, TypeError, ValueError):
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        return False


def check_output_escaping_cached(
    root: Path,
    paths: Iterable[Path],
    policy: SourceScanPolicy,
    cache_path: Path,
    *,
    force_fresh: bool = False,
) -> tuple[list[Finding], OutputEscapingCacheSummary]:
    """Reuse exact per-file findings; never cache a cross-file or tool result."""
    checkout = root.resolve(strict=True)
    header = _cache_header(checkout, policy)
    old_entries: dict[str, JsonValue] = {}
    invalidation: str | None = None
    if not force_fresh:
        old_entries, invalidation = _load_entries(cache_path, header)

    selected = sorted(
        (
            relative
            for relative in set(paths)
            if relative.suffix.lower() in policy.extensions
            and not any(
                matches_path(relative.as_posix(), pattern) for pattern in policy.exclude
            )
        ),
        key=lambda relative: relative.as_posix(),
    )
    new_entries: dict[str, JsonValue] = {}
    findings: list[Finding] = []
    hits = misses = 0
    old_paths = set(old_entries)
    current_paths = {relative.as_posix() for relative in selected}
    pruned = len(old_paths - current_paths)

    for relative in selected:
        name = relative.as_posix()
        path = checkout / relative
        if not path.is_file():
            continue
        raw = path.read_bytes()
        digest = _fingerprint(raw)
        cached = old_entries.get(name)
        if not force_fresh and cached is not None:
            try:
                cached_entry = _CacheEntryWire.model_validate(cached, strict=True)
            except (ValidationError, TypeError):
                cached_entry = None
            if cached_entry is not None and cached_entry.content_sha256 == digest:
                current_findings = _finding_rows(
                    name, cached_entry.findings, relative.suffix.lower()
                )
                hits += 1
                findings.extend(current_findings)
                new_entries[name] = cached
                continue
            if cached_entry is None:
                invalidation = "cached finding identity changed"

        misses += 1
        current_findings = output_escaping_findings_for_source(
            relative, _read_source(raw)
        )
        findings.extend(current_findings)
        new_entries[name] = {
            "content_sha256": digest,
            "findings": [finding.to_wire() for finding in current_findings],
        }

    saved = _write_cache(cache_path, header, new_entries)
    return findings, OutputEscapingCacheSummary(
        hits=hits,
        misses=misses,
        pruned=pruned,
        invalidation=invalidation,
        force_fresh=force_fresh,
        saved=saved,
    )
