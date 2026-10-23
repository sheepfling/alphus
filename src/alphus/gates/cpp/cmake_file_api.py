"""Typed entry points into CMake's File API codemodel replies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alphus.support.data_access import (
    load_json_object,
    require_json_array,
    require_json_object,
    require_json_string,
)


@dataclass(slots=True)
class CMakeConfiguration:
    name: str | None
    target_files: list[str]


@dataclass(slots=True)
class CMakeCodemodel:
    reply_directory: Path
    configurations: list[CMakeConfiguration]


def load_codemodel(build: Path) -> CMakeCodemodel:
    """Resolve the newest File API index and parse its target references."""
    reply_dir = build / ".cmake" / "api" / "v1" / "reply"
    indexes = sorted(
        reply_dir.glob("index-*.json"), key=lambda path: path.stat().st_mtime
    )
    if not indexes:
        raise ValueError(
            "CMake File API codemodel is missing; create query/codemodel-v2 and reconfigure"
        )
    index = load_json_object(indexes[-1])
    reply = require_json_object(
        index.get("reply", {}), "CMake File API index reply must be an object"
    )
    entry_value = reply.get("codemodel-v2")
    entry = (
        require_json_object(entry_value, "codemodel-v2 reply must be an object")
        if entry_value is not None
        else None
    )
    if entry is None:
        for raw_item in require_json_array(
            index.get("objects", []), "CMake File API objects must be an array"
        ):
            item = require_json_object(
                raw_item, "CMake File API object must be an object"
            )
            version = require_json_object(
                item.get("version", {}), "CMake object version must be an object"
            )
            if item.get("kind") == "codemodel" and version.get("major") == 2:
                entry = item
                break
    if entry is None:
        raise ValueError("latest CMake File API index has no codemodel-v2 reply")
    json_file = require_json_string(
        entry.get("jsonFile"), "codemodel-v2 reply needs jsonFile"
    )
    model = load_json_object(reply_dir / json_file)
    configurations: list[CMakeConfiguration] = []
    for raw_config in require_json_array(
        model.get("configurations", []), "CMake configurations must be an array"
    ):
        config = require_json_object(
            raw_config, "CMake configuration must be an object"
        )
        raw_name = config.get("name")
        name = (
            None
            if raw_name is None
            else require_json_string(
                raw_name, "CMake configuration name must be a string"
            )
        )
        target_files: list[str] = []
        for raw_target in require_json_array(
            config.get("targets", []), "CMake targets must be an array"
        ):
            target = require_json_object(
                raw_target, "CMake target entry must be an object"
            )
            target_files.append(
                require_json_string(
                    target.get("jsonFile"), "CMake target entry needs jsonFile"
                )
            )
        configurations.append(CMakeConfiguration(name, target_files))
    return CMakeCodemodel(reply_dir, configurations)
