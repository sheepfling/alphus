"""Generate the static built-in runner import manifest from theme mappings."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import NamedTuple

from scripts.generate_morphology_manifest import (
    feature_registrations,
    render_quality_rule_names,
)


class _RunnerModule(NamedTuple):
    """A theme's static import path, exported mapping, and selector keys."""

    theme: str
    module: str
    export: str
    selectors: tuple[str, ...]


def _literal_dict_keys(value: ast.expr, description: str) -> tuple[str, ...]:
    match value:
        case ast.Call(
            func=ast.Name(id="MappingProxyType"),
            args=[ast.Dict(keys=keys)],
            keywords=[],
        ):
            selectors: list[str] = []
            for key in keys:
                match key:
                    case ast.Constant(value=selector):
                        match selector:
                            case str():
                                selectors.append(selector)
                            case _:
                                raise ValueError(
                                    f"{description} must use literal string selectors"
                                )
                    case _:
                        raise ValueError(
                            f"{description} must use literal string selectors"
                        )
            return tuple(selectors)
        case _:
            raise ValueError(f"{description} must be a MappingProxyType literal")


def _runner_modules(root: Path) -> tuple[_RunnerModule, ...]:
    gates = root / "src" / "alphus" / "gates"
    modules: list[_RunnerModule] = []
    for path in sorted(gates.glob("*/runners.py")):
        theme = path.parent.name
        export = f"{theme.upper()}_RULE_RUNNERS"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        values: list[ast.expr] = []
        for statement in tree.body:
            match statement:
                case ast.AnnAssign(target=ast.Name(id=name), value=value) if (
                    name == export and value is not None
                ):
                    values.append(value)
                case _:
                    continue
        if len(values) != 1:
            raise ValueError(f"{path} must define exactly one {export} mapping")
        selectors = _literal_dict_keys(values[0], f"{path}:{export}")
        modules.append(
            _RunnerModule(
                theme,
                f"alphus.gates.{theme}.runners",
                export,
                selectors,
            )
        )
    if not modules:
        raise ValueError(f"no theme runners found under {gates}")
    return tuple(modules)


def _catalog_selectors(root: Path) -> frozenset[str]:
    path = root / "src" / "alphus" / "policy" / "_generated_quality_rule_names.py"
    source = render_quality_rule_names(root)
    tree = ast.parse(source, filename=str(path))
    for statement in tree.body:
        match statement:
            case ast.AnnAssign(
                target=ast.Name(id="QualityRuleName"),
                value=ast.Subscript(value=ast.Name(id="Literal"), slice=items),
            ):
                match items:
                    case ast.Tuple(elts=elements):
                        values = elements
                    case _:
                        values = (items,)
                selectors: set[str] = set()
                for item in values:
                    match item:
                        case ast.Constant(value=selector):
                            match selector:
                                case str():
                                    selectors.add(selector)
                                case _:
                                    raise ValueError(
                                        "QualityRuleName must contain literal string selectors"
                                    )
                        case _:
                            raise ValueError(
                                "QualityRuleName must contain literal string selectors"
                            )
                return frozenset(selectors)
            case _:
                continue
    raise ValueError(f"{path} must define QualityRuleName as a Literal")


def render_manifest(root: Path) -> str:
    """Render static imports after validating uniqueness and catalog coverage."""
    modules = _runner_modules(root)
    features = feature_registrations(root)
    owners: dict[str, str] = {}
    for module in modules:
        for selector in module.selectors:
            previous = owners.get(selector)
            if previous is not None:
                raise ValueError(
                    f"duplicate selector {selector!r} in themes "
                    f"{previous!r} and {module.theme!r}"
                )
            owners[selector] = module.theme
    for feature in features:
        previous = owners.get(feature.selector)
        if previous is not None:
            raise ValueError(
                f"duplicate selector {feature.selector!r} in theme {previous!r} "
                "and feature declaration"
            )
        owners[feature.selector] = feature.runner_module

    expected = _catalog_selectors(root)
    found = set(owners)
    missing = sorted(expected - found)
    unexpected = sorted(found - expected)
    if missing or unexpected:
        raise ValueError(
            f"runner/catalog mismatch: missing={missing}, unexpected={unexpected}"
        )

    lines = [
        '"""Generated by scripts/generate_runner_manifest.py; do not edit."""',
        "",
        "from collections.abc import Callable, Mapping, Sequence",
        "from importlib import import_module",
        "from pathlib import Path",
        "from types import MappingProxyType",
        "from typing import cast",
        "",
        "from alphus.config import QualityGateConfig, QualityRuleName",
        "from alphus.execution.results import RuleOutput",
    ]
    lines.extend(f"from {module.module} import {module.export}" for module in modules)
    lines.extend(
        [
            "",
            "_RuleRunner = Callable[[Path, Sequence[Path], QualityGateConfig], RuleOutput]",
            "",
        ]
    )
    for feature in features:
        function_name = f"_run_feature_{feature.selector.replace('-', '_')}"
        lines.extend(
            [
                "",
                f"def {function_name}(",
                "    root: Path, files: Sequence[Path], config: QualityGateConfig",
                ") -> RuleOutput:",
                f'    module = import_module("{feature.runner_module}")',
                f"    runner = cast(_RuleRunner, module.{feature.runner_name})",
                "    return runner(root, files, config)",
                "",
            ]
        )
    lines.extend(
        [
            "",
            (
                "_FEATURE_RULE_RUNNERS: Mapping[QualityRuleName, _RuleRunner] = "
                "MappingProxyType("
            ),
            "    {",
        ]
    )
    lines.extend(
        f'        "{feature.selector}": _run_feature_'
        f"{feature.selector.replace('-', '_')},"
        for feature in features
    )
    lines.extend(
        [
            "    }",
            ")",
            "",
            "RULE_RUNNERS: Mapping[QualityRuleName, _RuleRunner] = MappingProxyType(",
            "    {",
        ]
    )
    lines.extend(f"        **{module.export}," for module in modules)
    lines.append("        **_FEATURE_RULE_RUNNERS,")
    lines.extend(["    }", ")", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="repository root")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root: Path = args.root
    target = root / "src" / "alphus" / "execution" / "_generated_dispatch.py"
    try:
        expected = render_manifest(root)
    except (OSError, SyntaxError, ValueError) as error:
        print(f"runner manifest generation failed: {error}", file=sys.stderr)
        return 1

    if args.check:
        if not target.is_file() or target.read_text(encoding="utf-8") != expected:
            print(
                f"{target} is stale; run python -m scripts.generate_runner_manifest --root .",
                file=sys.stderr,
            )
            return 1
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
