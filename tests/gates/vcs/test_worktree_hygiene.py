"""The Git worktree CLI remains importable from the VCS gate package."""

from __future__ import annotations

import pytest

from alphus.gates.vcs.worktree_hygiene import main


def test_worktree_hygiene_help_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as result:
        main(["--help"])
    assert result.value.code == 0
