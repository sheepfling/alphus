"""Git-backed quality rules for ignores, attributes, and reachable history."""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path

from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.repository import GitAttributeRequirement
from alphus.support.git import git_output as _git
from alphus.support.git import run_git
from alphus.support.inventory import matches_path


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    language: str
    sample: str
    pattern: str


RULES = (
    IgnoreRule("repository", ".env", "**/.env"),
    IgnoreRule("repository", ".pypirc", "**/.pypirc"),
    IgnoreRule("python", ".venv/pyvenv.cfg", "**/.venv/**"),
    IgnoreRule("python", "__pycache__/module.pyc", "**/__pycache__/**"),
    IgnoreRule("python", ".pytest_cache/v/cache/nodeids", "**/.pytest_cache/**"),
    IgnoreRule("python", ".mypy_cache/3.11/module.data.json", "**/.mypy_cache/**"),
    IgnoreRule("python", ".ruff_cache/content", "**/.ruff_cache/**"),
    IgnoreRule("python", "dist/package.whl", "**/dist/**"),
    IgnoreRule("python", ".streamlit/secrets.toml", "**/.streamlit/secrets.toml"),
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


def _checkout(root: Path) -> Path:
    checkout = root.resolve(strict=True)
    if not checkout.is_dir():
        raise OSError(f"Git checkout root is not a directory: {checkout}")
    if _git(checkout, "rev-parse", "--is-inside-work-tree").strip() != b"true":
        raise OSError(f"not a Git working tree: {checkout}")
    prefix = _git(checkout, "rev-parse", "--show-prefix").decode().strip()
    if prefix:
        raise OSError(f"pass the Git checkout root, not a nested path: {checkout}")
    return checkout


def _tracked(root: Path) -> set[str]:
    return {
        part.decode("utf-8", "replace")
        for part in _git(root, "ls-files", "--cached", "-z").split(b"\0")
        if part
    }


def _selected_languages(paths: AbstractSet[str]) -> set[str]:
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


def check_ignores(root: Path, languages: Sequence[str] = ()) -> list[Finding]:
    """Check effective ignore rules and generated files already in the index."""
    root = _checkout(root)
    tracked = _tracked(root)
    selected = set(languages) if languages else _selected_languages(tracked)
    rules = [r for r in RULES if r.language == "repository" or r.language in selected]
    findings: list[Finding] = []
    for rule in rules:
        for sample in (rule.sample, f"nested/{rule.sample}"):
            result = run_git(
                root, "check-ignore", "--quiet", "--no-index", "--", sample
            )
            if result.returncode == 1:
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            Scope(rule.language),
                            Framework.GIT,
                            Category.HYGIENE,
                            "missing-ignore-rule",
                        ),
                        path=sample,
                        message=f"Generated {rule.language} path is not ignored by Git",
                    )
                )
            elif result.returncode:
                raise OSError(
                    "git check-ignore failed: "
                    + result.stderr.decode("utf-8", "replace").strip()
                )
    for path in sorted(tracked):
        for rule in rules:
            if matches_path(path, rule.pattern):
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            Scope(rule.language),
                            Framework.GIT,
                            Category.HYGIENE,
                            "tracked-generated-file",
                        ),
                        path=path,
                        message="Generated path is tracked; an ignore rule does not untrack it",
                    )
                )
                break
    return findings


def check_attributes(
    root: Path, requirements: Sequence[GitAttributeRequirement] = ()
) -> list[Finding]:
    """Check committed root attributes and each declared effective attribute."""
    root = _checkout(root)
    tracked = _tracked(root)
    findings: list[Finding] = []
    if ".gitattributes" not in tracked:
        findings.append(
            Finding(
                rule_id=rule_tag(
                    Scope.REPOSITORY,
                    Framework.GIT,
                    Category.HYGIENE,
                    "attributes-file-untracked",
                ),
                path=".gitattributes",
                message="Root .gitattributes must be tracked",
            )
        )
    for requirement in requirements:
        result = run_git(
            root,
            "check-attr",
            "-z",
            requirement.attribute,
            "--",
            requirement.path,
        )
        if result.returncode:
            raise OSError(
                "git check-attr failed: "
                + result.stderr.decode("utf-8", "replace").strip()
            )
        fields = result.stdout.split(b"\0")
        if len(fields) != 4 or fields[-1] != b"":
            raise OSError("git check-attr returned an unexpected response")
        actual = fields[2].decode("utf-8", "replace")
        if actual != requirement.value:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.REPOSITORY,
                        Framework.GIT,
                        Category.HYGIENE,
                        "attribute-mismatch",
                    ),
                    path=requirement.path,
                    message=(
                        f"Git attribute {requirement.attribute} is {actual!r}; "
                        f"expected {requirement.value!r}"
                    ),
                )
            )
    return findings


def check_history(root: Path, max_blob_mib: float = 5.0) -> list[Finding]:
    """Inspect all reachable refs for large blobs and generated-file paths."""
    root = _checkout(root)
    if max_blob_mib <= 0:
        raise ValueError("max_blob_mib must be positive")
    findings: list[Finding] = []
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
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            Scope.REPOSITORY,
                            Framework.GIT,
                            Category.HYGIENE,
                            "large-historical-blob",
                        ),
                        path=objects[oid] or ".",
                        message=(
                            f"{int(size) / 1048576:.1f} MiB blob in Git history "
                            f"({oid.decode()[:12]})"
                        ),
                    )
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
                findings.append(
                    Finding(
                        rule_id=rule_tag(
                            Scope(rule.language),
                            Framework.GIT,
                            Category.HYGIENE,
                            "historical-artifact",
                        ),
                        path=path,
                        message="Generated path was committed in reachable Git history",
                    )
                )
                break
    return findings
