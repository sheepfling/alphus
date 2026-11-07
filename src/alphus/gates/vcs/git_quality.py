"""Git-backed quality rules for ignores, attributes, and reachable history."""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from alphus.contracts.complaints import ComplaintContract, ComplaintEntry
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.policy.repository import (
    GitAttributeRequirement,
    TrackedGeneratedOutput,
    TrackedGeneratedProvenance,
)
from alphus.support.git import git_output as _git
from alphus.support.git import run_git
from alphus.support.inventory import matches_path

ALPHUS_COMPLAINT_CONTRACTS: Final = (
    ComplaintContract(
        name="git-repository-checks",
        emitters=("git-ignores", "git-attributes", "git-history"),
        entries=(
            ComplaintEntry(
                emitter="git-ignores",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.GIT,
                    Category.HYGIENE,
                    "missing-ignore-rule",
                ),
            ),
            ComplaintEntry(
                emitter="git-ignores",
                tag=RuleTag(
                    Scope.PYTHON, Framework.GIT, Category.HYGIENE, "missing-ignore-rule"
                ),
            ),
            ComplaintEntry(
                emitter="git-ignores",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.GIT,
                    Category.HYGIENE,
                    "missing-ignore-rule",
                ),
            ),
            ComplaintEntry(
                emitter="git-ignores",
                tag=RuleTag(
                    Scope.CPP, Framework.GIT, Category.HYGIENE, "missing-ignore-rule"
                ),
            ),
            ComplaintEntry(
                emitter="git-ignores",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.GIT,
                    Category.HYGIENE,
                    "tracked-generated-file",
                ),
            ),
            ComplaintEntry(
                emitter="git-ignores",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.GIT,
                    Category.HYGIENE,
                    "tracked-generated-file",
                ),
            ),
            ComplaintEntry(
                emitter="git-ignores",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.GIT,
                    Category.HYGIENE,
                    "tracked-generated-file",
                ),
            ),
            ComplaintEntry(
                emitter="git-ignores",
                tag=RuleTag(
                    Scope.CPP, Framework.GIT, Category.HYGIENE, "tracked-generated-file"
                ),
            ),
            ComplaintEntry(
                emitter="git-ignores",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.GIT,
                    Category.HYGIENE,
                    "tracked-generated-output",
                ),
            ),
            ComplaintEntry(
                emitter="git-attributes",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.GIT,
                    Category.HYGIENE,
                    "attributes-file-untracked",
                ),
            ),
            ComplaintEntry(
                emitter="git-attributes",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.GIT,
                    Category.HYGIENE,
                    "attribute-mismatch",
                ),
            ),
            ComplaintEntry(
                emitter="git-history",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.GIT,
                    Category.HYGIENE,
                    "large-historical-blob",
                ),
            ),
            ComplaintEntry(
                emitter="git-history",
                tag=RuleTag(
                    Scope.REPOSITORY,
                    Framework.GIT,
                    Category.HYGIENE,
                    "historical-artifact",
                ),
            ),
            ComplaintEntry(
                emitter="git-history",
                tag=RuleTag(
                    Scope.PYTHON, Framework.GIT, Category.HYGIENE, "historical-artifact"
                ),
            ),
            ComplaintEntry(
                emitter="git-history",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.GIT,
                    Category.HYGIENE,
                    "historical-artifact",
                ),
            ),
            ComplaintEntry(
                emitter="git-history",
                tag=RuleTag(
                    Scope.CPP, Framework.GIT, Category.HYGIENE, "historical-artifact"
                ),
            ),
        ),
    ),
)


def _git_contract_rule_id(
    emitter: Literal["git-ignores", "git-attributes", "git-history"],
    scope: Scope,
    complaint: str,
) -> str:
    """Resolve one emitted identity from the shared static complaint contract."""
    for contract in ALPHUS_COMPLAINT_CONTRACTS:
        if emitter not in contract.emitters:
            continue
        for entry in contract.entries:
            if (
                entry.emitter == emitter
                and entry.tag.scope is scope
                and entry.tag.complaint == complaint
            ):
                return entry.tag.rule_id
    raise ValueError(
        f"Git complaint {complaint!r} is not declared for {emitter} in {scope}"
    )


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


def check_ignores(
    root: Path,
    languages: Sequence[str] = (),
    generated_outputs: Sequence[TrackedGeneratedOutput] = (),
    generated_provenance: Sequence[TrackedGeneratedProvenance] = (),
) -> list[Finding]:
    """Check ignore rules and explicit tracked-output contracts."""
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
                        rule_id=_git_contract_rule_id(
                            "git-ignores",
                            Scope(rule.language),
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
    native_generated_paths: set[str] = set()
    intentional_paths = {item.path for item in generated_provenance}
    for path in sorted(tracked):
        for rule in rules:
            if matches_path(path, rule.pattern):
                native_generated_paths.add(path)
                contract = next(
                    (
                        item
                        for item in generated_outputs
                        if path not in intentional_paths
                        and matches_path(path, item.pattern)
                    ),
                    None,
                )
                contract_evidence = (
                    ""
                    if contract is None
                    else (
                        f"; declared {contract.classification} from "
                        f"{contract.generator} under contract {contract.pattern!r}"
                    )
                )
                findings.append(
                    Finding(
                        rule_id=_git_contract_rule_id(
                            "git-ignores",
                            Scope(rule.language),
                            "tracked-generated-file",
                        ),
                        path=path,
                        message=(
                            "Generated path is tracked; an ignore rule does not "
                            f"untrack it{contract_evidence}"
                        ),
                    )
                )
                break
    for path in sorted(tracked - intentional_paths - native_generated_paths):
        for contract in generated_outputs:
            if matches_path(path, contract.pattern):
                findings.append(
                    Finding(
                        rule_id=_git_contract_rule_id(
                            "git-ignores",
                            Scope.REPOSITORY,
                            "tracked-generated-output",
                        ),
                        path=path,
                        severity="info",
                        message=(
                            f"Tracked {contract.classification} matches output contract "
                            f"{contract.pattern!r} from {contract.generator}; review "
                            "whether this path has declared intentional provenance"
                        ),
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
                rule_id=_git_contract_rule_id(
                    "git-attributes", Scope.REPOSITORY, "attributes-file-untracked"
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
                    rule_id=_git_contract_rule_id(
                        "git-attributes", Scope.REPOSITORY, "attribute-mismatch"
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
                        rule_id=_git_contract_rule_id(
                            "git-history", Scope.REPOSITORY, "large-historical-blob"
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
                        rule_id=_git_contract_rule_id(
                            "git-history",
                            Scope(rule.language),
                            "historical-artifact",
                        ),
                        path=path,
                        message="Generated path was committed in reachable Git history",
                    )
                )
                break
    return findings
