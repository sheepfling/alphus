"""Git ignore and infrequent full-history hygiene audits."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from alphus.support.inventory import matches_path


@dataclass(frozen=True)
class IgnoreRule:
    language: str
    sample: str
    pattern: str


RULES = (
    IgnoreRule("common", ".env", "**/.env"),
    IgnoreRule("python", ".venv/pyvenv.cfg", "**/.venv/**"),
    IgnoreRule("python", "__pycache__/module.pyc", "**/__pycache__/**"),
    IgnoreRule("python", ".pytest_cache/v/cache/nodeids", "**/.pytest_cache/**"),
    IgnoreRule("python", ".mypy_cache/3.11/module.data.json", "**/.mypy_cache/**"),
    IgnoreRule("python", ".ruff_cache/content", "**/.ruff_cache/**"),
    IgnoreRule("python", "dist/package.whl", "**/dist/**"),
    IgnoreRule("javascript", "node_modules/pkg/index.js", "**/node_modules/**"),
    IgnoreRule("javascript", "project.tsbuildinfo", "**/*.tsbuildinfo"),
    IgnoreRule("javascript", ".eslintcache", "**/.eslintcache"),
    IgnoreRule("cpp", "build/CMakeCache.txt", "**/build/**"),
    IgnoreRule("cpp", "cmake-build-debug/CMakeCache.txt", "**/cmake-build-*/**"),
    IgnoreRule("cpp", "CMakeFiles/compiler.dir/main.o", "**/CMakeFiles/**"),
    IgnoreRule("cpp", "main.o", "**/*.o"),
    IgnoreRule("cpp", "main.obj", "**/*.obj"),
    IgnoreRule("cpp", "main.pdb", "**/*.pdb"),
    IgnoreRule("cpp", "main.exe", "**/*.exe"),
    IgnoreRule("cpp", "libmain.a", "**/*.a"),
)
LANGUAGES = ("python", "javascript", "cpp")


def _git(root: Path, *args: str, input_data: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, input=input_data, capture_output=True, check=False
        )
    except FileNotFoundError as error:
        raise RuntimeError("Git is required for repository hygiene checks") from error
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _checkout(root: Path) -> Path:
    root = root.resolve()
    top = Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if top != root:
        raise RuntimeError(f"pass the Git checkout root: {top}")
    return top


def _tracked(root: Path) -> set[str]:
    return {
        part.decode("utf-8", "replace")
        for part in _git(root, "ls-files", "--cached", "-z").split(b"\0")
        if part
    }


def _selected_languages(paths: set[str]) -> set[str]:
    selected: set[str] = set()
    if any(p.endswith(".py") or p == "pyproject.toml" for p in paths):
        selected.add("python")
    if any(
        p.endswith((".js", ".jsx", ".ts", ".tsx")) or p == "package.json" for p in paths
    ):
        selected.add("javascript")
    if any(
        p.endswith(
            (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx", "CMakeLists.txt")
        )
        for p in paths
    ):
        selected.add("cpp")
    return selected


def check_ignores(root: Path, languages: set[str] | None = None) -> list[str]:
    """Check effective ignore rules and generated files already in the index."""
    root = _checkout(root)
    tracked = _tracked(root)
    selected = _selected_languages(tracked) if languages is None else languages
    rules = [r for r in RULES if r.language == "common" or r.language in selected]
    issues: list[str] = []
    for rule in rules:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", "--", rule.sample],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if result.returncode == 1:
            issues.append(f"{rule.language}: add an ignore rule for {rule.sample}")
        elif result.returncode:
            raise RuntimeError(
                "git check-ignore failed: "
                + result.stderr.decode("utf-8", "replace").strip()
            )
        for path in sorted(tracked):
            if matches_path(path, rule.pattern):
                issues.append(
                    f"{rule.language}: {path} is tracked; an ignore rule does not untrack it"
                )
    return issues


def check_history(root: Path, max_blob_mib: float = 5.0) -> list[str]:
    """Inspect all reachable refs for large blobs and generated-file paths."""
    root = _checkout(root)
    if max_blob_mib <= 0:
        raise ValueError("max_blob_mib must be positive")
    issues: list[str] = []
    objects: dict[bytes, str] = {}
    for line in _git(root, "rev-list", "--objects", "--all").splitlines():
        oid, _, path = line.partition(b" ")
        objects.setdefault(oid, path.decode("utf-8", "replace"))
    if objects:
        batch = _git(
            root,
            "cat-file",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
            input_data=b"\n".join(objects) + b"\n",
        )
        limit = max_blob_mib * 1024 * 1024
        for line in batch.splitlines():
            oid, kind, size = line.split()
            if kind == b"blob" and int(size) >= limit:
                issues.append(
                    f"large historical blob: {int(size) / 1048576:.1f} MiB "
                    f"{objects[oid]} ({oid.decode()[:12]})"
                )
    paths = {
        raw.strip(b"\n").decode("utf-8", "replace")
        for raw in _git(root, "log", "--all", "--name-only", "-z", "--format=").split(
            b"\0"
        )
        if raw.strip(b"\n")
    }
    for path in sorted(paths):
        for rule in RULES:
            if matches_path(path, rule.pattern):
                issues.append(f"historical {rule.language} artifact: {path}")
                break
    return issues


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit Git ignores or reachable history"
    )
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="Git checkout root"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ignore = commands.add_parser("ignore", help="fast current-checkout ignore audit")
    ignore.add_argument("--languages", nargs="+", choices=LANGUAGES)
    history = commands.add_parser("history", help="infrequent all-ref history audit")
    history.add_argument("--max-blob-mib", type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        if args.command == "ignore":
            issues = check_ignores(
                args.root, set(args.languages) if args.languages else None
            )
        else:
            issues = check_history(args.root, args.max_blob_mib)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Git hygiene audit failed: {error}", file=sys.stderr)
        return 2
    for issue in issues:
        print(issue)
    if not issues:
        print(f"Git {args.command} audit passed")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
