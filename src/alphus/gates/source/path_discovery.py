"""Route path-discovery checks to the owning source language."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from alphus.config import QualityGateConfig
from alphus.contracts.complaints import ComplaintContract, ComplaintEntry
from alphus.contracts.findings import Finding, SourceFinding
from alphus.contracts.rule_tags import Category, Framework, RuleTag, Scope
from alphus.gates.languages.javascript.path_discovery import (
    js_inspection_findings,
    js_path_findings,
)
from alphus.gates.languages.python.path_discovery import (
    python_inspection_findings,
    python_path_findings,
)
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.policy.base import require_policy
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.morphology import (
    ClaimKind,
    DetectionMechanism,
    EvaluationMaturity,
    RuleMorphology,
)
from alphus.policy.sources import PathDiscoveryPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_python_source, read_utf8_sig_text


@dataclass(frozen=True, slots=True)
class PathFindingIdentity:
    """Named category and complaint for one path-discovery message."""

    category: Category
    complaint: str


ALPHUS_COMPLAINT_CONTRACTS: Final = (
    ComplaintContract(
        name="path-discovery",
        emitters=("path-discovery",),
        entries=(
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "implicit-module-root",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "implicit-module-root",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "implicit-working-directory",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "implicit-working-directory",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "implicit-git-root",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "implicit-git-root",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "url-string-inspection",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "url-string-inspection",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "path-string-inspection",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "path-string-inspection",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "raw-platform-detection",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "raw-platform-detection",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "import-path-mutation",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.NONE,
                    Category.ARCHITECTURE,
                    "import-path-mutation",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "implicit-executable-root",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.NONE,
                    Category.PORTABILITY,
                    "implicit-executable-root",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.PYTHON,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "path-string-comparison",
                ),
            ),
            ComplaintEntry(
                emitter="path-discovery",
                tag=RuleTag(
                    Scope.JAVASCRIPT,
                    Framework.NONE,
                    Category.CORRECTNESS,
                    "path-string-comparison",
                ),
            ),
        ),
    ),
)

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="path-discovery",
    policy_field="path_discovery",
    policy_model=PathDiscoveryPolicy,
    output_shape="findings",
    summary="Reviews Python filesystem discovery and path handling patterns.",
    applies_to=("python",),
    domains=(),
    requires_files=True,
)

ALPHUS_MORPHOLOGY: Final = RuleMorphology(
    selector="path-discovery",
    finding_ids=(
        RuleTag(
            Scope.PYTHON, Framework.NONE, Category.PORTABILITY, "implicit-module-root"
        ),
        RuleTag(
            Scope.JAVASCRIPT,
            Framework.NONE,
            Category.PORTABILITY,
            "implicit-module-root",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.PORTABILITY,
            "implicit-working-directory",
        ),
        RuleTag(
            Scope.JAVASCRIPT,
            Framework.NONE,
            Category.PORTABILITY,
            "implicit-working-directory",
        ),
        RuleTag(
            Scope.PYTHON, Framework.NONE, Category.PORTABILITY, "implicit-git-root"
        ),
        RuleTag(
            Scope.JAVASCRIPT, Framework.NONE, Category.PORTABILITY, "implicit-git-root"
        ),
        RuleTag(
            Scope.PYTHON, Framework.NONE, Category.CORRECTNESS, "url-string-inspection"
        ),
        RuleTag(
            Scope.JAVASCRIPT,
            Framework.NONE,
            Category.CORRECTNESS,
            "url-string-inspection",
        ),
        RuleTag(
            Scope.PYTHON, Framework.NONE, Category.PORTABILITY, "path-string-inspection"
        ),
        RuleTag(
            Scope.JAVASCRIPT,
            Framework.NONE,
            Category.PORTABILITY,
            "path-string-inspection",
        ),
        RuleTag(
            Scope.PYTHON, Framework.NONE, Category.PORTABILITY, "raw-platform-detection"
        ),
        RuleTag(
            Scope.JAVASCRIPT,
            Framework.NONE,
            Category.PORTABILITY,
            "raw-platform-detection",
        ),
        RuleTag(
            Scope.PYTHON, Framework.NONE, Category.ARCHITECTURE, "import-path-mutation"
        ),
        RuleTag(
            Scope.JAVASCRIPT,
            Framework.NONE,
            Category.ARCHITECTURE,
            "import-path-mutation",
        ),
        RuleTag(
            Scope.PYTHON,
            Framework.NONE,
            Category.PORTABILITY,
            "implicit-executable-root",
        ),
        RuleTag(
            Scope.JAVASCRIPT,
            Framework.NONE,
            Category.PORTABILITY,
            "implicit-executable-root",
        ),
        RuleTag(
            Scope.PYTHON, Framework.NONE, Category.CORRECTNESS, "path-string-comparison"
        ),
        RuleTag(
            Scope.JAVASCRIPT,
            Framework.NONE,
            Category.CORRECTNESS,
            "path-string-comparison",
        ),
    ),
    finding_contracts=("path-discovery",),
    concern="implicit-path-roots-and-string-inspection",
    claim_kind=ClaimKind.RISK,
    claim="Reviews source for implicit path roots and bounded string-based path inspection.",
    mechanisms=(DetectionMechanism.BOUNDED_HEURISTIC,),
    inspected_scope=("configured-source-files", "path-and-url-expressions"),
    languages_formats=("python", "javascript"),
    evidence_kinds=("source-pattern", "source-line"),
    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,
)


def _path_rule_id(scope: Scope, identity: PathFindingIdentity) -> str:
    for contract in ALPHUS_COMPLAINT_CONTRACTS:
        for entry in contract.entries:
            if (
                entry.emitter == "path-discovery"
                and entry.tag.scope is scope
                and entry.tag.category is identity.category
                and entry.tag.complaint == identity.complaint
            ):
                return entry.tag.rule_id
    raise ValueError(
        f"no path-discovery finding contract for {scope.value}/{identity.complaint}"
    )


_PATH_TAGS: Mapping[str, PathFindingIdentity] = MappingProxyType(
    {
        "module URL used as an implicit path root": PathFindingIdentity(
            Category.PORTABILITY, "implicit-module-root"
        ),
        "module directory used as an implicit path root": PathFindingIdentity(
            Category.PORTABILITY, "implicit-module-root"
        ),
        "current working directory used as an implicit path root": PathFindingIdentity(
            Category.PORTABILITY, "implicit-working-directory"
        ),
        "Git checkout discovery used as an implicit path root": PathFindingIdentity(
            Category.PORTABILITY, "implicit-git-root"
        ),
        "URL prefix test; parse with URL": PathFindingIdentity(
            Category.CORRECTNESS, "url-string-inspection"
        ),
        "URL scheme substring test; parse with URL": PathFindingIdentity(
            Category.CORRECTNESS, "url-string-inspection"
        ),
        "slash prefix test; parse the declared path flavor": PathFindingIdentity(
            Category.PORTABILITY, "path-string-inspection"
        ),
        "separator rewrite; parse the declared path flavor": PathFindingIdentity(
            Category.PORTABILITY, "path-string-inspection"
        ),
        "module __file__ used to infer a parent root": PathFindingIdentity(
            Category.PORTABILITY, "implicit-module-root"
        ),
        "raw os.name comparison; use a shared platform probe": PathFindingIdentity(
            Category.PORTABILITY, "raw-platform-detection"
        ),
        "sys.path mutated for local module discovery": PathFindingIdentity(
            Category.ARCHITECTURE, "import-path-mutation"
        ),
        "sys.executable used to derive a path": PathFindingIdentity(
            Category.PORTABILITY, "implicit-executable-root"
        ),
        "Path.cwd() used as an implicit path root": PathFindingIdentity(
            Category.PORTABILITY, "implicit-working-directory"
        ),
        "os.getcwd() used as an implicit path root": PathFindingIdentity(
            Category.PORTABILITY, "implicit-working-directory"
        ),
        "path string comparison; use as_posix() at the boundary": PathFindingIdentity(
            Category.CORRECTNESS, "path-string-comparison"
        ),
        "URL prefix test; parse with urlsplit": PathFindingIdentity(
            Category.CORRECTNESS, "url-string-inspection"
        ),
        "URL scheme substring test; parse with urlsplit": PathFindingIdentity(
            Category.CORRECTNESS, "url-string-inspection"
        ),
    }
)


def check_path_discovery(
    root: Path, paths: Iterable[Path], policy: PathDiscoveryPolicy
) -> list[Finding]:
    """Report configured implicit path roots and string-based path inspection."""
    findings: list[Finding] = []
    checkout = root.resolve(strict=True)
    for relative in sorted(paths):
        name = relative.as_posix()
        if any(matches_path(name, pattern) for pattern in policy.exclude):
            continue
        suffix = relative.suffix.lower()
        if suffix not in policy.extensions:
            continue
        path = checkout / relative
        if not path.is_file():
            continue
        source = (
            read_python_source(path) if suffix == ".py" else read_utf8_sig_text(path)
        )
        inspect_strings = not any(
            matches_path(name, pattern) for pattern in policy.inspection_exclude
        )
        source_findings: list[SourceFinding]
        if suffix == ".py":
            source_findings = python_path_findings(source)
            if inspect_strings:
                source_findings += python_inspection_findings(source)
            scope = Scope.PYTHON
        else:
            source_findings = js_path_findings(source)
            if inspect_strings:
                source_findings += js_inspection_findings(source)
            scope = Scope.JAVASCRIPT
        for source_finding in source_findings:
            identity = _PATH_TAGS[source_finding.message]
            findings.append(
                Finding(
                    rule_id=_path_rule_id(scope, identity),
                    path=name,
                    line=source_finding.line,
                    message=source_finding.message,
                )
            )
    return findings


def run_path_discovery_rule(
    root: Path, paths: Sequence[Path], config: QualityGateConfig
) -> list[Finding]:
    """Adapt the feature-owned strict source scope to both language checks."""
    return run_path_discovery_feature(
        root, paths, resolve_path_discovery_policy(config)
    )


def resolve_path_discovery_policy(config: QualityGateConfig) -> PathDiscoveryPolicy:
    """Resolve the strict cross-language path-discovery policy."""
    return require_policy(config.checks.path_discovery, "path_discovery")


def run_path_discovery_feature(
    root: Path, paths: Sequence[Path], policy: PathDiscoveryPolicy
) -> list[Finding]:
    """Dispatch path-discovery evidence to language-specific providers."""
    return check_path_discovery(root, paths, policy)


ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_path_discovery_feature,
    policy_resolver=resolve_path_discovery_policy,
)
