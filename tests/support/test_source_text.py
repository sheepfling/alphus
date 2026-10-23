"""Python source decoding follows the interpreter's PEP 263 rules."""

from __future__ import annotations

from pathlib import Path

from alphus.support.source_text import read_python_source


def test_python_source_reader_accepts_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "bom.py"
    path.write_bytes(b"\xef\xbb\xbfvalue = 1\n")
    assert read_python_source(path) == "value = 1\n"


def test_python_source_reader_honors_coding_cookie(tmp_path: Path) -> None:
    path = tmp_path / "latin.py"
    path.write_bytes(b"# coding: latin-1\n# caf\xe9\nvalue = 1\n")
    assert "café" in read_python_source(path)
