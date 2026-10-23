"""Python source decoding follows the interpreter's PEP 263 rules."""

from __future__ import annotations

from pathlib import Path

from alphus.support.source_text import (
    read_python_source,
    read_utf8_sig_text,
    read_utf8_text,
)


def test_python_source_reader_accepts_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "bom.py"
    path.write_bytes(b"\xef\xbb\xbfvalue = 1\n")
    assert read_python_source(path) == "value = 1\n"


def test_python_source_reader_honors_coding_cookie(tmp_path: Path) -> None:
    path = tmp_path / "latin.py"
    path.write_bytes(b"# coding: latin-1\n# caf\xe9\nvalue = 1\n")
    assert "café" in read_python_source(path)


def test_explicit_utf8_reader(tmp_path: Path) -> None:
    path = tmp_path / "policy.toml"
    path.write_text("name = 'café'\n", encoding="utf-8")
    assert read_utf8_text(path) == "name = 'café'\n"


def test_bom_aware_reader_and_explicit_replacement(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_bytes(b"\xef\xbb\xbfhello\n")
    assert read_utf8_sig_text(path) == "hello\n"
    path.write_bytes(b"bad: \xff")
    assert read_utf8_text(path, errors="replace") == "bad: \ufffd"
