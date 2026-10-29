"""Repository file inventory can be supplied by another VCS adapter."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from alphus.policy.sources import FileInventoryPolicy
from alphus.support.inventory import candidate_files, tracked_files


class SampleBackend:
    def files(self, root: Path) -> Sequence[Path]:
        return [Path("src/sample.py"), Path("../escape.py")]

    def tracked(self, root: Path) -> Sequence[Path]:
        return [Path("src/sample.py"), Path("../escape.py")]


def test_alternate_inventory_backend_supplies_safe_relative_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "sample.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    backend = SampleBackend()
    policy = FileInventoryPolicy(include=("src/**/*.py",), exclude=())
    assert candidate_files(tmp_path, policy, backend=backend) == [Path("src/sample.py")]
    assert tracked_files(tmp_path, backend=backend) == [Path("src/sample.py")]


def test_git_inventory_excludes_symlinks_and_generated_paths(tmp_path: Path) -> None:
    """Default text-rule inventory contains in-root regular files only."""
    subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True
    )
    authored = tmp_path / "src" / "authored.py"
    authored.parent.mkdir()
    authored.write_text("value = 1\n", encoding="utf-8")
    generated = tmp_path / "build" / "generated" / "output.py"
    generated.parent.mkdir(parents=True)
    generated.write_text("value = 2\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("value = 3\n", encoding="utf-8")
    try:
        (tmp_path / "src" / "linked.py").symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")

    selected = candidate_files(
        tmp_path,
        FileInventoryPolicy(include=("**/*.py",), exclude=("build/generated/**",)),
    )

    assert selected == [Path("src/authored.py")]
