"""Filesystem fixture showing why parse and provenance need the same bytes."""

from __future__ import annotations

import hashlib
from pathlib import Path


def _parse_bytes(contents: bytes) -> bytes:
    return contents


def test_independent_path_reads_can_describe_different_input_bytes(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.dat"
    input_path.write_bytes(b"version-one")

    parsed_value = _parse_bytes(input_path.read_bytes())
    input_path.write_bytes(b"version-two")
    digest_of_reread_path = hashlib.sha256(input_path.read_bytes()).digest()

    assert hashlib.sha256(parsed_value).digest() != digest_of_reread_path


def test_captured_bytes_keep_parse_and_digest_bound_after_path_changes(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.dat"
    input_path.write_bytes(b"version-one")

    snapshot = input_path.read_bytes()
    parsed_value = _parse_bytes(snapshot)
    input_path.write_bytes(b"version-two")
    digest_of_snapshot = hashlib.sha256(snapshot).digest()

    assert hashlib.sha256(parsed_value).digest() == digest_of_snapshot
