"""Source revision probes remain optional and accept other VCS providers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alphus.support import version_control


def test_git_revision_probe_uses_the_shared_git_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def git_value(root: Path, *arguments: str) -> str | None:
        assert root == tmp_path
        return {
            ("rev-parse", "--is-inside-work-tree"): "true",
            ("symbolic-ref", "--quiet", "--short", "HEAD"): "main",
            ("rev-parse", "HEAD"): "abc123",
        }.get(arguments)

    monkeypatch.setattr(version_control, "git_value", git_value)
    identity = version_control.GitVersionControlProvider().identify(tmp_path)
    assert identity == version_control.VersionControlIdentity("git", "main", "abc123")


def test_svn_revision_probe_reads_local_xml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def svn_info(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert args == (["svn", "info", "--xml", "."],)
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(
            args[0],
            0,
            b'<info><entry revision="42"><relative-url>^/trunk</relative-url></entry></info>',
            b"",
        )

    monkeypatch.setattr(version_control.subprocess, "run", svn_info)
    identity = version_control.SvnVersionControlProvider().identify(tmp_path)
    assert identity == version_control.VersionControlIdentity("svn", "^/trunk", "42")


def test_missing_vcs_has_no_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(version_control, "git_value", lambda *_: None)

    def missing_svn(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("svn")

    monkeypatch.setattr(version_control.subprocess, "run", missing_svn)
    assert version_control.capture_version_control(tmp_path) is None
