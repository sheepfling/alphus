"""Require an owned, dated removal plan for Python compatibility forwarders."""

from __future__ import annotations

import argparse
import ast
import keyword
import re
import sys
import tomllib
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import cast

_COMPATIBILITY_MARKER = re.compile(
    r"^(?:compatibility|compat|legacy|deprecated)\s+"
    r"(?:imports?|re[- ]?exports?|forwarders?|shims?)\b",
    re.IGNORECASE,
)
_COMMENT_MARKER = re.compile(
    r"\b(?:compatibility|compat|legacy|deprecated)\s+"
    r"(?:imports?|re[- ]?exports?|forwarders?|shims?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Forwarder:
    """A source module that only forwards imports or declares that purpose."""

    module: str
    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class RemovalPlan:
    """The replacement, accountable owner, and last allowed day."""

    module: str
    replacement: str
    owner: str
    remove_by: date


def _valid_dotted_name(value: str) -> bool:
    return bool(value) and all(
        part.isidentifier() and not keyword.iskeyword(part) for part in value.split(".")
    )


def _valid_reference(value: str) -> bool:
    module, separator, object_name = value.partition(":")
    return _valid_dotted_name(module) and (
        not separator or _valid_dotted_name(object_name)
    )


def _is_main_guard(node: ast.If, imported: AbstractSet[str]) -> bool:
    test = node.test
    if (
        node.orelse
        or type(test) is not ast.Compare
        or type(test.left) is not ast.Name
        or test.left.id != "__name__"
        or len(test.ops) != 1
        or type(test.ops[0]) is not ast.Eq
        or len(test.comparators) != 1
        or type(test.comparators[0]) is not ast.Constant
        or test.comparators[0].value != "__main__"
        or len(node.body) != 1
    ):
        return False
    statement = node.body[0]
    call: ast.Call | None = None
    if type(statement) is ast.Expr and type(statement.value) is ast.Call:
        call = statement.value
    elif (
        type(statement) is ast.Raise
        and type(statement.exc) is ast.Call
        and type(statement.exc.func) is ast.Name
        and statement.exc.func.id == "SystemExit"
        and len(statement.exc.args) == 1
        and type(statement.exc.args[0]) is ast.Call
    ):
        call = statement.exc.args[0]
    return call is not None and type(call.func) is ast.Name and call.func.id in imported


def _is_export_assignment(node: ast.stmt, imported: AbstractSet[str]) -> bool:
    if type(node) is ast.Assign:
        if all(
            type(target) is ast.Name and target.id == "__all__"
            for target in node.targets
        ):
            return True
        return (
            type(node.value) is ast.Name
            and node.value.id in imported
            and all(type(target) is ast.Name for target in node.targets)
        )
    return (
        type(node) is ast.AnnAssign
        and type(node.target) is ast.Name
        and node.target.id == "__all__"
    )


def _forwarder_reason(tree: ast.Module, source: str, filename: str) -> str | None:
    body = tree.body
    if (
        body
        and type(body[0]) is ast.Expr
        and type(body[0].value) is ast.Constant
        and type(body[0].value.value) is str
    ):
        body = body[1:]
    imported: set[str] = set()
    forwards = False
    wildcard = False
    for node in body:
        if type(node) is ast.ImportFrom and node.module == "__future__":
            continue
        if type(node) is ast.ImportFrom:
            forwards = True
            for alias in node.names:
                if alias.name == "*":
                    wildcard = True
                else:
                    imported.add(alias.asname or alias.name)
        elif type(node) is ast.Import:
            forwards = True
            imported.update(
                alias.asname or alias.name.split(".")[0] for alias in node.names
            )
    if not forwards:
        return None
    docstring = ast.get_docstring(tree) or ""
    comments = "\n".join(
        line for line in source.splitlines() if line.lstrip().startswith("#")
    )
    first_line = docstring.splitlines()[0] if docstring else ""
    if _COMPATIBILITY_MARKER.search(first_line) or _COMMENT_MARKER.search(comments):
        return "marked compatibility import"
    if wildcard:
        return "wildcard import"
    if filename in {"__init__.py", "__main__.py"}:
        return None
    if all(
        type(node) in (ast.Import, ast.ImportFrom, ast.Pass)
        or _is_export_assignment(node, imported)
        or type(node) is ast.If
        and _is_main_guard(node, imported)
        for node in body
    ):
        return "import-only forwarder"
    return None


def discover_forwarders(
    source_root: Path,
) -> tuple[tuple[Forwarder, ...], tuple[str, ...]]:
    """Find forwarding modules without importing their source code."""
    root = source_root.resolve(strict=True)
    found: list[Forwarder] = []
    issues: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative.as_posix())
        except (OSError, UnicodeError, SyntaxError) as error:
            issues.append(
                f"{relative.as_posix()}: cannot inspect Python source: {error}"
            )
            continue
        reason = _forwarder_reason(tree, source, path.name)
        if reason is None:
            continue
        parts = relative.with_suffix("").parts
        module = ".".join(parts[:-1] if path.name == "__init__.py" else parts)
        found.append(Forwarder(module, relative.as_posix(), reason))
    return tuple(found), tuple(issues)


def load_removal_plans(path: Path) -> tuple[dict[str, RemovalPlan], tuple[str, ...]]:
    """Load an explicit, strict TOML removal plan."""
    try:
        with path.open("rb") as stream:
            document = cast(dict[str, object], tomllib.load(stream))
    except (OSError, tomllib.TOMLDecodeError) as error:
        return {}, (f"{path}: cannot read removal plan: {error}",)
    issues: list[str] = []
    if (
        set(document) != {"schema_version", "forwarders"}
        or type(document.get("schema_version")) is not int
        or document["schema_version"] != 1
    ):
        issues.append(f"{path}: expected schema_version = 1 and a forwarders list")
    entries = document.get("forwarders")
    if type(entries) is not list:
        return {}, (*issues, f"{path}: forwarders must be a TOML array of tables")
    plans: dict[str, RemovalPlan] = {}
    for index, value in enumerate(cast(list[object], entries), start=1):
        label = f"{path}: forwarders[{index}]"
        if type(value) is not dict:
            issues.append(f"{label}: require module, replacement, owner, and remove_by")
            continue
        entry = cast(dict[str, object], value)
        if set(entry) != {"module", "replacement", "owner", "remove_by"}:
            issues.append(f"{label}: require module, replacement, owner, and remove_by")
            continue
        module = entry["module"]
        replacement = entry["replacement"]
        owner = entry["owner"]
        remove_by = entry["remove_by"]
        if type(module) is not str or not _valid_dotted_name(module):
            issues.append(f"{label}: module must be a dotted Python name")
            continue
        if type(replacement) is not str or not _valid_reference(replacement):
            issues.append(
                f"{label}: replacement must be an importable Python reference"
            )
            continue
        if type(owner) is not str or not owner.strip():
            issues.append(f"{label}: owner must be nonempty")
            continue
        if type(remove_by) is not date:
            issues.append(f"{label}: remove_by must be a TOML date")
            continue
        if module in plans:
            issues.append(f"{label}: duplicate plan for {module}")
            continue
        plans[module] = RemovalPlan(module, replacement, owner.strip(), remove_by)
    return plans, tuple(issues)


def check_forwarders(
    source_root: Path,
    plan_path: Path | None = None,
    *,
    today: date | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return failures and visible active plans for every forwarding module."""
    forwarders, discovery_issues = discover_forwarders(source_root)
    plans, plan_issues = (
        load_removal_plans(plan_path) if plan_path is not None else ({}, ())
    )
    current = today or datetime.now(timezone.utc).date()
    issues = [*discovery_issues, *plan_issues]
    planned: list[str] = []
    found_modules = {forwarder.module for forwarder in forwarders}
    for forwarder in forwarders:
        plan = plans.get(forwarder.module)
        if plan is None:
            issues.append(
                f"{forwarder.path}: {forwarder.reason} {forwarder.module} has no removal plan"
            )
        elif plan.remove_by <= current:
            issues.append(
                f"{forwarder.path}: removal plan for {forwarder.module} "
                f"expired on {plan.remove_by.isoformat()}"
            )
        else:
            planned.append(
                f"{forwarder.module} -> {plan.replacement}; "
                f"owner={plan.owner}; remove_by={plan.remove_by.isoformat()}"
            )
    for module in plans.keys() - found_modules:
        issues.append(
            f"{module}: stale removal plan; forwarding module no longer exists"
        )
    return tuple(sorted(issues)), tuple(sorted(planned))


def main(argv: Sequence[str] | None = None) -> int:
    """Check forwarding modules and report their removal commitments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    options = parser.parse_args(argv)
    try:
        issues, planned = check_forwarders(options.source_root, options.plan)
    except OSError as error:
        print(f"Python compatibility imports: {error}", file=sys.stderr)
        return 2
    for entry in planned:
        print(f"PLAN {entry}")
    for issue in issues:
        print(f"FAIL {issue}")
    print(
        f"Python compatibility imports: {len(planned)} planned, {len(issues)} issue(s)"
    )
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
