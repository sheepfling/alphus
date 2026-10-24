"""Effective Git attribute policy checks use Git's own attribute parser."""

from __future__ import annotations

import subprocess
from pathlib import Path

from alphus.gates.vcs.git_quality import check_attributes
from alphus.policy.repository import GitAttributeRequirement


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)


def test_attributes_rule_reports_untracked_file_and_effective_mismatch(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "--quiet")
    expected = GitAttributeRequirement(
        path="javascript/example.js", attribute="eol", value="lf"
    )

    missing = check_attributes(tmp_path, (expected,))
    assert [item.rule_id for item in missing] == [
        "alphus/repository/git/hygiene/attributes-file-untracked",
        "alphus/repository/git/hygiene/attribute-mismatch",
    ]

    (tmp_path / ".gitattributes").write_text(
        "/javascript/** text eol=crlf\n", encoding="utf-8"
    )
    _git(tmp_path, "add", ".gitattributes")
    mismatch = check_attributes(tmp_path, (expected,))
    assert [item.message for item in mismatch] == [
        "Git attribute eol is 'crlf'; expected 'lf'"
    ]

    (tmp_path / ".gitattributes").write_text(
        "/javascript/** text eol=lf\n", encoding="utf-8"
    )
    assert check_attributes(tmp_path, (expected,)) == []
