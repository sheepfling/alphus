"""Repository file inventory can be supplied by another VCS adapter."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

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
