"""Consumer config recipes are small, validated, and safe to generate."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from alphus.cli import main
from alphus.config import load_config_stream
from alphus.policy.recipes import RECIPES, render_recipe


@pytest.mark.parametrize("recipe", tuple(RECIPES)[:-1])
def test_builtin_recipes_parse_and_resolve(recipe: str) -> None:
    policy = load_config_stream(StringIO(render_recipe(recipe)))
    assert policy.orchestration is not None
    assert policy.orchestration.profiles


def test_custom_recipe_composes_language_and_named_tool() -> None:
    document = render_recipe("custom", add_languages=("python",), add_tools=("rumdl",))
    assert document == (
        'schema_version = 1\nlanguages = ["python"]\ntools = ["rumdl"]\n'
    )
    assert load_config_stream(StringIO(document)).orchestration is not None


@pytest.mark.parametrize(
    ("name", "languages", "tools", "message"),
    [
        ("missing", (), (), "unknown config recipe"),
        ("custom", (), (), "needs --add-language"),
        ("python", ("python",), (), "must not repeat"),
        ("python", (), ("ruff",), "must not repeat"),
    ],
)
def test_invalid_recipe_selection_is_rejected(
    name: str, languages: tuple[str, ...], tools: tuple[str, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        render_recipe(name, add_languages=languages, add_tools=tools)


def test_init_config_writes_and_requires_explicit_overwrite(tmp_path: Path) -> None:
    arguments = [
        "--root",
        str(tmp_path),
        "--init-config",
        "python",
        "--config",
        "gates.toml",
    ]
    assert main(arguments) == 0
    target = tmp_path / "gates.toml"
    assert target.read_text(encoding="utf-8") == render_recipe("python")
    assert main([*arguments, "--add-tool", "rumdl"]) != 0
    assert target.read_text(encoding="utf-8") == render_recipe("python")
    assert main([*arguments, "--add-tool", "rumdl", "--overwrite-config"]) == 0
    assert target.read_text(encoding="utf-8") == render_recipe(
        "python", add_tools=("rumdl",)
    )
    assert main(["--root", str(tmp_path), "--config", "gates.toml", "--plan"]) == 0


def test_init_config_rejects_path_outside_root(tmp_path: Path) -> None:
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "--config",
                "../outside.toml",
                "--init-config",
                "starter",
            ]
        )
        != 0
    )
    assert not (tmp_path.parent / "outside.toml").exists()
