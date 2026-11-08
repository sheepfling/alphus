"""Verify typed registration for Python message-producing checks."""

from pathlib import Path

from alphus.config import QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.languages.python import runtime_types, script_policy
from alphus.plugins.builtin import MessageBuiltinFeature
from alphus.policy.sources import RuntimeTypePolicy, ScriptPolicy


def test_message_features_keep_strict_policies_and_direct_adapters(
    tmp_path: Path,
) -> None:
    runtime_policy = RuntimeTypePolicy(extensions=(".py",))
    script_policy_config = ScriptPolicy(
        extensions=(".sh",),
        cmd_router_line_limit=20,
        python_module_prefix="alphus",
        launcher_message="use Python modules for operational scripts",
        cmd_message="use a Python module for operational commands",
    )
    config = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "runtime_types": runtime_policy,
                "script_policy": script_policy_config,
            },
        },
        strict=True,
    )

    assert isinstance(runtime_types.ALPHUS_FEATURE, MessageBuiltinFeature)
    assert isinstance(script_policy.ALPHUS_FEATURE, MessageBuiltinFeature)
    assert type(runtime_types.resolve_runtime_types_policy(config)) is RuntimeTypePolicy
    assert type(script_policy.resolve_script_policy(config)) is ScriptPolicy
    assert run_builtin_rule("runtime-types", tmp_path, (), config) == []
    assert run_builtin_rule("script-policy", tmp_path, (), config) == []
    assert runtime_types.run_runtime_types_rule(tmp_path, (), config) == []
    assert script_policy.run_script_policy_rule(tmp_path, (), config) == []
