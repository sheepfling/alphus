"""Verify related prose checks share one typed policy contract."""

from pathlib import Path

from alphus.config import QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.review import prose_as_control, rendered_value_reparsed
from alphus.plugins.builtin import FindingBuiltinFeature
from alphus.policy.review import ProseAsControlPolicy


def test_related_prose_selectors_share_the_typed_configured_policy(
    tmp_path: Path,
) -> None:
    policy = ProseAsControlPolicy(
        extensions=(".py",),
        source_paths=("src/render/*.py",),
        rendered_value_helpers=("render_latex",),
    )
    config = QualityGateConfig.model_validate(
        {"schema_version": 1, "checks": {"prose_as_control": policy}},
        strict=True,
    )

    assert isinstance(prose_as_control.ALPHUS_FEATURE, FindingBuiltinFeature)
    assert isinstance(rendered_value_reparsed.ALPHUS_FEATURE, FindingBuiltinFeature)
    assert (
        type(prose_as_control.resolve_prose_as_control_policy(config))
        is ProseAsControlPolicy
    )
    assert (
        type(rendered_value_reparsed.resolve_rendered_value_reparsed_policy(config))
        is ProseAsControlPolicy
    )
    assert run_builtin_rule("prose-as-control", tmp_path, (), config) == []
    assert run_builtin_rule("rendered-value-reparsed", tmp_path, (), config) == []
