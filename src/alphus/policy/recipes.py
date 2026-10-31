"""Small named starter policies assembled from the native tool catalog."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType

from alphus.policy.native_tools import native_tool_policy, native_tools_for_languages


@dataclass(frozen=True, slots=True)
class ConfigRecipe:
    languages: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()


RECIPES = MappingProxyType(
    {
        "starter": ConfigRecipe(tools=("rumdl",)),
        "python": ConfigRecipe(languages=("python",)),
        "markdown": ConfigRecipe(languages=("markdown",)),
        "toml": ConfigRecipe(languages=("toml",)),
        "yaml": ConfigRecipe(languages=("yaml",)),
        "json": ConfigRecipe(languages=("json",)),
        "javascript": ConfigRecipe(languages=("javascript",)),
        "polyglot": ConfigRecipe(
            languages=("python", "markdown", "toml", "json", "javascript")
        ),
        "custom": ConfigRecipe(),
    }
)


def render_recipe(
    name: str,
    *,
    add_languages: Sequence[str] = (),
    add_tools: Sequence[str] = (),
) -> str:
    """Render and validate an editable two- or three-line policy."""
    try:
        recipe = RECIPES[name]
    except KeyError as error:
        supported = ", ".join(RECIPES)
        raise ValueError(
            f"unknown config recipe {name!r}; choose from {supported}"
        ) from error
    languages = (*recipe.languages, *add_languages)
    tools = (*recipe.tools, *add_tools)
    if not languages and not tools:
        raise ValueError("custom recipe needs --add-language or --add-tool")
    lines = ["schema_version = 1"]
    if languages:
        lines.append(f"languages = {json.dumps(languages)}")
    if tools:
        lines.append(f"tools = {json.dumps(tools)}")
    document = "\n".join(lines) + "\n"
    selected = (*native_tools_for_languages(languages), *tools) if languages else tools
    native_tool_policy(selected)
    return document
