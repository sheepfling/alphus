"""Build portable gate identities for immutable profile history."""

from __future__ import annotations

import hashlib
import json

from alphus.config import QualityGateConfig
from alphus.contracts.findings import Severity
from alphus.execution.profile_history import GateManifestEntry
from alphus.plugins.registry import enabled_plugin_registry
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
        builtin = RULE_SPECS.get(step.rule)
        if builtin is not None:
            gate_id = f"alphus/rule/{step.rule}"
            policy = getattr(config.checks, builtin.policy_field)
            identity = {
                "rule": step.rule,
                "policy": policy.model_dump(mode="json")
                if policy is not None
                else None,
                "files": config.files.model_dump(mode="json")
                if config.files is not None
                else None,
                "severity": step.severity,
                "priority": step.priority,
                "rollout": step.rollout,
                "failure_threshold": threshold,
            }
        else:
            binding = enabled_plugin_registry(config.plugins).get(step.rule)
            if binding is None:
                raise ValueError(f"unknown or disabled rule selector {step.rule!r}")
            gate_id = f"alphus/plugin/{step.rule}"
            identity = {
                "rule": step.rule,
                "plugin": {
                    "name": binding.plugin.name,
                    "api_version": binding.plugin.api_version,
                    "distribution": binding.distribution,
                    "distribution_version": binding.distribution_version,
                },
                "settings": config.plugins.settings_for(step.rule),
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
