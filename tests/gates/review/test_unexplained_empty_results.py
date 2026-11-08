from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import QualityGateConfig, UnexplainedEmptyResultPolicy
from alphus.gates.review.unexplained_empty_results import (
    ALPHUS_FEATURE,
    check_unexplained_empty_results,
    empty_result_branches,
    resolve_unexplained_empty_results_policy,
)
from alphus.plugins.builtin import FindingBuiltinFeature


def test_registration_binds_finding_runner_to_empty_result_policy() -> None:
    assert isinstance(ALPHUS_FEATURE, FindingBuiltinFeature)
    assert ALPHUS_FEATURE.policy_resolver is resolve_unexplained_empty_results_policy
    assert ALPHUS_FEATURE.definition.policy_model is UnexplainedEmptyResultPolicy


def test_resolver_returns_the_strict_declared_empty_result_policy() -> None:
    config = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {"unexplained_empty_results": _policy()},
        },
        strict=True,
    )
    policy = resolve_unexplained_empty_results_policy(config)

    assert type(policy) is UnexplainedEmptyResultPolicy
    assert policy == _policy()


def _policy(
    *,
    nonempty_inputs: tuple[str, ...] = ("records",),
    exclude: tuple[str, ...] = (),
) -> UnexplainedEmptyResultPolicy:
    return UnexplainedEmptyResultPolicy(
        extensions=(".py",),
        source_paths=("src/parser/*.py",),
        nonempty_inputs=nonempty_inputs,
        unavailable_flags=("inferred_schema",),
        exclude=exclude,
    )


def test_detects_nonempty_input_with_unknown_inference_returning_empty() -> None:
    source = """\
def parse(records):
    if records and not inferred_schema:
        return []
    return parse_rows(records)
"""
    assert empty_result_branches(source, _policy()) == [
        (3, "records", "inferred_schema")
    ]


def test_ignores_valid_empty_input_and_nonempty_result_branches() -> None:
    valid_empty = """\
def parse(records):
    if not records:
        return []
"""
    nonempty_result = """\
def parse(records):
    if records and not inferred_schema:
        raise UnknownFormatError()
"""
    assert empty_result_branches(valid_empty, _policy()) == []
    assert empty_result_branches(nonempty_result, _policy()) == []


def test_configuration_is_explicit_and_names_are_validated() -> None:
    with pytest.raises(
        ValidationError, match="input and inference names must be identifiers"
    ):
        _policy(nonempty_inputs=("records[0]",))


def test_reports_configured_source_scope_and_exclusions(tmp_path: Path) -> None:
    path = tmp_path / "src/parser/table.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "def parse(records):\n"
        "    if records and not inferred_schema:\n"
        "        return []\n",
        encoding="utf-8",
    )
    findings = check_unexplained_empty_results(
        tmp_path, (Path("src/parser/table.py"),), _policy()
    )
    assert len(findings) == 1
    assert findings[0].rule_id == (
        "alphus/python/none/validation/unexplained-empty-result"
    )
    assert not check_unexplained_empty_results(
        tmp_path,
        (Path("src/parser/table.py"),),
        _policy(exclude=("src/parser/**",)),
    )
