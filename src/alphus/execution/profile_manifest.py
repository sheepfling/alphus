"""Build portable gate identities for immutable profile history."""

from __future__ import annotations

import hashlib
import json

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Severity
from alphus.execution.profile_history import GateManifestEntry
from alphus.policy.catalog import RULE_SPECS
from alphus.policy.orchestration import CommandRunStep, RuleRunStep


def gate_manifest_entry(
    step: RuleRunStep | CommandRunStep,
    config: QualityGateConfig,
    *,
    failure_threshold: Severity | None = None,
) -> GateManifestEntry:
    """Identify a gate without confusing its display name with its semantics."""
    threshold = (
        failure_threshold
        if failure_threshold is not None
        else config.orchestration.failure_threshold
        if config.orchestration is not None
        else None
    )
    if isinstance(step, RuleRunStep):
        gate_id = f"alphus/rule/{step.rule}"
        field = RULE_SPECS[step.rule].policy_field
        policy = getattr(config.checks, field)
        identity = {
            "rule": step.rule,
            "policy": policy.model_dump(mode="json") if policy is not None else None,
            "files": config.files.model_dump(mode="json")
            if config.files is not None
            else None,
            "severity": step.severity,
            "priority": step.priority,
            "rollout": step.rollout,
            "failure_threshold": threshold,
        }
    else:
        gate_id = step.gate_id
        identity = {
            "argv": step.argv,
            "fix_argv": step.fix_argv,
            "working_directory": step.working_directory,
            "files": step.files.model_dump(mode="json") if step.files else None,
            "timeout_seconds": step.timeout_seconds,
            "rollout": step.rollout,
            "failure_threshold": threshold,
        }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return GateManifestEntry(
        step_name=step.name,
        gate_id=gate_id,
        kind=step.kind,
        gate_policy_sha256=digest,
    )
