"""Language profile fragments compose without broadening policy file access."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import load_config, load_config_stream


def _policy(
    root: Path, include: str = 'orchestration_files = ["languages/markdown.toml"]'
) -> Path:
    (root / "languages").mkdir()
    (root / "languages/markdown.toml").write_text(
        '[[orchestration.steps]]\nkind = "command"\nname = "Markdown"\n'
        'argv = ["rumdl", "check", "{files}"]\n'
        'fix_argv = ["rumdl", "fmt", "{files}"]\n'
        'files = { include = ["*.md"] }\n'
        '[[orchestration.profiles]]\nname = "markdown"\nsteps = ["Markdown"]\n',
        encoding="utf-8",
    )
    policy = root / "quality.toml"
    policy.write_text(
        f"schema_version = 1\n{include}\n"
        '[files]\ninclude = ["*.md"]\n'
        '[orchestration]\ndefault_profile = "check"\n'
        '[[orchestration.profiles]]\nname = "check"\n'
        'includes = ["markdown"]\n',
        encoding="utf-8",
    )
    return policy


def test_language_fragment_resolves_from_policy_directory(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    plan = load_config(policy).orchestration
    assert plan is not None
    selected = plan.resolve_profile("check")
    assert selected is not None
    assert selected.profiles == ("markdown", "check")
    assert selected.steps == ("Markdown",)


@pytest.mark.parametrize(
    "fragment",
    ["../other.toml", "/outside.toml", "languages/../other.toml", "..\\other.toml"],
)
def test_language_fragment_rejects_escape(tmp_path: Path, fragment: str) -> None:
    policy = _policy(tmp_path, f"orchestration_files = [{json.dumps(fragment)}]")
    with pytest.raises(ValueError, match="relative POSIX path"):
        load_config(policy)


def test_language_fragment_rejects_other_policy_sections(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    (tmp_path / "languages/markdown.toml").write_text(
        "[orchestration]\n[files]\ninclude = []\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(policy)


def test_language_fragment_rejects_repeated_path(tmp_path: Path) -> None:
    policy = _policy(
        tmp_path,
        'orchestration_files = ["languages/markdown.toml", "languages/markdown.toml"]',
    )
    with pytest.raises(ValidationError, match="must not repeat a path"):
        load_config(policy)


def test_language_fragment_duplicate_step_is_invalid(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    with policy.open("a", encoding="utf-8") as stream:
        stream.write(
            '[[orchestration.steps]]\nkind = "command"\nname = "Markdown"\n'
            'argv = ["rumdl", "check", "."]\n'
        )
    with pytest.raises(
        ValidationError, match="orchestration step names must be unique"
    ):
        load_config(policy)


def test_stream_loader_rejects_unresolved_fragment_list(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    with pytest.raises(ValidationError, match="orchestration_files"):
        load_config_stream(StringIO(policy.read_text(encoding="utf-8")))
