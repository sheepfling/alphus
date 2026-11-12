"""Explicitly run synthetic subprocess environment regressions; never scan a consumer."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn, TypedDict

SETTING = "ALPHUS_RECIPE_COMMAND_SETTING"
SAFE_VALUES = ("", "a-only", "b-only", "shared", "outer", "inner", "original")
REQUIREMENT_GROUPS = {
    "path": ("PATH", "PATHEXT", "SystemRoot"),
    "locale": ("LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_MESSAGES"),
    "proxies": (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ),
    "toolchain": (
        "CC",
        "CXX",
        "CPP",
        "CFLAGS",
        "CXXFLAGS",
        "LDFLAGS",
        "SDKROOT",
        "DEVELOPER_DIR",
        "CMAKE_PREFIX_PATH",
        "PKG_CONFIG_PATH",
        "VIRTUAL_ENV",
        "PYTHONPATH",
        "JAVA_HOME",
        "CARGO_HOME",
        "RUSTUP_HOME",
    ),
}


class Observation(TypedDict):
    command: str
    present: bool
    value: str | None
    effective: str
    requirements_preserved: dict[str, bool]
    children: list[Observation]


class Restoration(TypedDict):
    initial: str | None
    during: Observation
    normal: Observation
    exceptional: Observation
    nested: Observation
    restored: Observation


class RecipeChecks(TypedDict):
    expected_ambient_leak_observed: bool
    command_local_isolated: bool
    explicit_environments_isolated: bool
    nested_boundaries_respected: bool
    unset_differs_from_empty: bool
    intentional_inheritance_retained: bool
    temporary_settings_restored: bool
    adjacent_commands_isolated: bool
    parent_environment_restored: bool
    ordinary_requirements_preserved: bool


class RecipeReport(TypedDict):
    recipe: str
    synthetic_keys: list[str]
    ambient_leak: list[Observation]
    command_local: list[Observation]
    explicit_child_env: list[Observation]
    nested_boundaries: list[Observation]
    unset_and_empty: list[Observation]
    intentional_inheritance: list[Observation]
    temporary_restoration: list[Restoration]
    adjacent_commands: list[Observation]
    checks: RecipeChecks
    passed: bool


@contextmanager
def temporary_setting(value: str | None) -> Iterator[None]:
    """Restore both absence and empty values, even across nested exceptions.

    This illustrates legacy single-threaded cleanup, not a concurrency-safe
    substitute for command-local options or explicit child environments.
    """
    if value is not None and value not in SAFE_VALUES:
        raise ValueError("Only declared synthetic values are permitted")
    present = SETTING in os.environ
    previous = os.environ.get(SETTING)
    try:
        if value is None:
            os.environ.pop(SETTING, None)
        else:
            os.environ[SETTING] = value
        yield
    finally:
        if present:
            assert previous is not None
            os.environ[SETTING] = previous
        else:
            os.environ.pop(SETTING, None)


def child_environment(value: str | None) -> dict[str, str]:
    """Copy ordinary requirements, changing only the declared command setting."""
    if value is not None and value not in SAFE_VALUES:
        raise ValueError("Only declared synthetic values are permitted")
    environment = os.environ.copy()
    if value is None:
        environment.pop(SETTING, None)
    else:
        environment[SETTING] = value
    return environment


def _requirements() -> dict[str, str | None]:
    return {
        key: os.environ.get(key) for keys in REQUIREMENT_GROUPS.values() for key in keys
    }


def _launch(
    command: str,
    expected: Mapping[str, str | None],
    *,
    option: str | None = None,
    environment: Mapping[str, str] | None = None,
    descendants: str = "none",
) -> Observation:
    argv = [
        sys.executable,
        "-I",
        str(Path(__file__).resolve()),
        "--child",
        command,
        "--descendants",
        descendants,
    ]
    if option is not None:
        argv.extend(("--setting", option))
    # Requirement values travel only over an anonymous stdin pipe. They are
    # compared in memory, never included in argv, output, errors or artifacts.
    result = subprocess.run(
        argv,
        env=environment,
        input=json.dumps(expected),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Synthetic child failed; environment details withheld")
    return json.loads(result.stdout)


def _observe_child(args: argparse.Namespace) -> Observation:
    expected = json.load(sys.stdin)
    value = os.environ.get(SETTING)
    if value is not None and value not in SAFE_VALUES:
        raise ValueError("Unexpected synthetic setting; value withheld")
    preserved = {
        group: all(os.environ.get(key) == expected[key] for key in keys)
        for group, keys in REQUIREMENT_GROUPS.items()
    }
    children: list[Observation] = []
    if args.descendants in {"inherit", "split"}:
        children.append(_launch("grandchild-a", expected))
    if args.descendants == "split":
        children.append(
            _launch("grandchild-b", expected, environment=child_environment(None))
        )
    return {
        "command": args.child,
        "present": SETTING in os.environ,
        "value": value,
        "effective": args.setting
        if args.setting is not None
        else (value if value is not None else "default"),
        "requirements_preserved": preserved,
        "children": children,
    }


def _restoration(
    initial: str | None, expected: Mapping[str, str | None]
) -> Restoration:
    with temporary_setting(initial):
        with temporary_setting("a-only"):
            during = _launch("a", expected)
        normal = _launch("b", expected)
        try:
            with temporary_setting("b-only"):
                raise RuntimeError("Synthetic failure")
        except RuntimeError:
            pass
        exceptional = _launch("b", expected)
        with temporary_setting("outer"):
            try:
                with temporary_setting("inner"):
                    raise RuntimeError("Synthetic nested failure")
            except RuntimeError:
                pass
            nested = _launch("a", expected)
        restored = _launch("c", expected)
    return {
        "initial": initial,
        "during": during,
        "normal": normal,
        "exceptional": exceptional,
        "nested": nested,
        "restored": restored,
    }


def _all_preserved(value: object) -> bool:
    if isinstance(value, dict):
        checks = value.get("requirements_preserved", {})
        return all(checks.values()) and all(_all_preserved(v) for v in value.values())
    if isinstance(value, list):
        return all(_all_preserved(v) for v in value)
    return True


def run_recipe() -> RecipeReport:
    """Run controlled processes only. The ambient leak is an expected witness."""
    before = os.environ.copy()
    expected = _requirements()
    with temporary_setting(None):
        # Bad: A's setting leaks to unrelated commands B and C, and a grandchild.
        with temporary_setting("a-only"):
            ambient = [
                _launch(
                    name, expected, descendants="inherit" if name == "b" else "none"
                )
                for name in ("a", "b", "c")
            ]

        # Good: CLI settings belong to each invocation, not to the parent env.
        command_local = [
            _launch("a", expected, option="a-only", descendants="inherit"),
            _launch("b", expected, option="b-only"),
            _launch("c", expected),
        ]

        # Good even with a polluted parent: copy everything, then override/pop
        # only this setting for each child. Never replace PATH/etc with env={}.
        with temporary_setting("a-only"):
            explicit = [
                _launch("a", expected, environment=child_environment("a-only")),
                _launch("b", expected, environment=child_environment(None)),
                _launch("c", expected, environment=child_environment("b-only")),
            ]
            parent_unchanged = os.environ.get(SETTING) == "a-only"
            nested = [
                _launch(
                    "a",
                    expected,
                    environment=child_environment("a-only"),
                    descendants="split",
                ),
                _launch(
                    "b",
                    expected,
                    environment=child_environment(None),
                    descendants="inherit",
                ),
            ]

        unset_empty = [
            _launch("a", expected, environment=child_environment(None)),
            _launch("b", expected, environment=child_environment("")),
            _launch("c", expected, option="", environment=child_environment(None)),
        ]
        with temporary_setting("shared"):
            intentional = [
                _launch("a", expected, descendants="inherit"),
                _launch("b", expected),
            ]
        restoration = [
            _restoration(value, expected) for value in (None, "", "original")
        ]
        adjacent = [
            _launch("a", expected, environment=child_environment("a-only")),
            _launch("b", expected),
        ]

    restored_parent = os.environ == before
    checks: RecipeChecks = {
        "expected_ambient_leak_observed": (
            [child["value"] for child in ambient] == ["a-only"] * 3
            and ambient[1]["children"][0]["value"] == "a-only"
        ),
        "command_local_isolated": (
            [child["effective"] for child in command_local]
            == ["a-only", "b-only", "default"]
            and all(not child["present"] for child in command_local)
            and not command_local[0]["children"][0]["present"]
        ),
        "explicit_environments_isolated": (
            [child["value"] for child in explicit] == ["a-only", None, "b-only"]
            and parent_unchanged
        ),
        "nested_boundaries_respected": (
            [child["value"] for child in nested[0]["children"]] == ["a-only", None]
            and nested[1]["value"] is None
            and nested[1]["children"][0]["value"] is None
        ),
        "unset_differs_from_empty": (
            not unset_empty[0]["present"]
            and unset_empty[0]["effective"] == "default"
            and unset_empty[1]["present"]
            and unset_empty[1]["effective"] == ""
            and not unset_empty[2]["present"]
            and unset_empty[2]["effective"] == ""
        ),
        "intentional_inheritance_retained": (
            all(child["value"] == "shared" for child in intentional)
            and intentional[0]["children"][0]["value"] == "shared"
        ),
        "temporary_settings_restored": all(
            case["during"]["value"] == "a-only"
            and case["nested"]["value"] == "outer"
            and all(
                case[stage]["value"] == case["initial"]
                and case[stage]["present"] == (case["initial"] is not None)
                for stage in ("normal", "exceptional", "restored")
            )
            for case in restoration
        ),
        "adjacent_commands_isolated": adjacent[0]["value"] == "a-only"
        and not adjacent[1]["present"],
        "parent_environment_restored": restored_parent,
        "ordinary_requirements_preserved": True,
    }
    report: RecipeReport = {
        "recipe": "environment-boundary",
        "synthetic_keys": [SETTING],
        "ambient_leak": ambient,
        "command_local": command_local,
        "explicit_child_env": explicit,
        "nested_boundaries": nested,
        "unset_and_empty": unset_empty,
        "intentional_inheritance": intentional,
        "temporary_restoration": restoration,
        "adjacent_commands": adjacent,
        "checks": checks,
        "passed": False,
    }
    checks["ordinary_requirements_preserved"] = _all_preserved(report)
    report["passed"] = all(checks.values())
    return report


class SafeArgumentParser(argparse.ArgumentParser):
    """Do not echo potentially private values from mistaken CLI arguments."""

    def error(self, message: str) -> NoReturn:
        self.exit(2, "Synthetic recipe arguments rejected; details withheld\n")


def main() -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument(
        "--child", choices=("a", "b", "c", "grandchild-a", "grandchild-b")
    )
    parser.add_argument("--setting", choices=SAFE_VALUES)
    parser.add_argument(
        "--descendants", choices=("none", "inherit", "split"), default="none"
    )
    args = parser.parse_args()
    try:
        report = _observe_child(args) if args.child else run_recipe()
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ):
        # Do not include exception details: subprocess/JSON failures may contain
        # private stdin or environment values. Report only the controlled failure.
        print(
            json.dumps(
                {"error": "Synthetic recipe failed; environment details withheld"}
            )
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if args.child or report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
