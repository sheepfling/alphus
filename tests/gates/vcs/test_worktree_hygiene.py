"""The Git worktree CLI remains importable from the VCS gate package."""

from __future__ import annotations

from pathlib import Path

import pytest

import alphus.gates.vcs.worktree_hygiene as worktree_hygiene
from alphus.gates.vcs.worktree_hygiene import (
    DirectorySize,
    WorktreeRecord,
    _inspect,
    _logical_size,
    _unregistered,
    main,
)


def test_worktree_hygiene_help_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as result:
        main(["--help"])
    assert result.value.code == 0


def test_logical_size_returns_named_immutable_metrics(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_bytes(b"module")
    (tmp_path / "README.md").write_bytes(b"readme")

    result = _logical_size(tmp_path)

    assert isinstance(result, DirectorySize)
    assert result.total_bytes == len(b"module") + len(b"readme")
    assert result.file_count == 2
    assert dict(result.largest_top_level) == {
        "src": len(b"module"),
        "README.md": len(b"readme"),
    }
    assert result.errors == ()
    with pytest.raises(TypeError):
        result.largest_top_level["new"] = 1  # type: ignore[index]


def test_inspect_keeps_status_and_size_errors_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "worktree"
    checkout.mkdir()
    record: WorktreeRecord = {
        "path": str(checkout),
        "head": None,
        "branch": None,
        "detached": True,
        "locked": False,
        "prunable": False,
    }
    monkeypatch.setattr(
        worktree_hygiene,
        "_git",
        lambda *_args, **_kwargs: worktree_hygiene.subprocess.CompletedProcess(
            (), 1, stdout=b"", stderr=b"status unavailable"
        ),
    )
    monkeypatch.setattr(
        worktree_hygiene,
        "_logical_size",
        lambda _root: DirectorySize(0, 0, {}, ("size unavailable",)),
    )

    result = _inspect(tmp_path, record, None, True, ())

    assert result["errors"] == ["status unavailable", "size unavailable"]


def test_nested_scan_roots_do_not_double_count_a_covered_orphan(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    orphan = storage / "orphan"
    build = orphan / "build"
    build.mkdir(parents=True)
    (build / "artifact.bin").write_bytes(b"x" * 100)

    for roots in ([storage, orphan], [orphan, storage]):
        unregistered = _unregistered(roots, [], measure_size=True)

        assert [item["path"] for item in unregistered] == [str(orphan)]
        assert unregistered[0]["logical_bytes"] == 100
        assert unregistered[0]["file_count"] == 1
