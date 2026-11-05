"""Tests for repository-local links in the documentation index."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest


def test_documentation_index_local_links_resolve(pytestconfig: pytest.Config) -> None:
    index = Path(pytestconfig.rootpath) / "docs/README.md"
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", index.read_text(encoding="utf-8"))

    local_targets = [
        unquote(urlsplit(link).path)
        for link in links
        if not urlsplit(link).scheme and not link.startswith("//")
    ]

    assert local_targets
    for target in local_targets:
        resolved = (index.parent / target).resolve()
        assert resolved.is_file() or resolved.is_dir(), target
