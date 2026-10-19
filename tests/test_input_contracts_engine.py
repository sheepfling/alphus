"""Exercise local input contracts without claiming whole-program mutation proof."""

from pathlib import Path
from textwrap import dedent

import pytest

from alphus.config import InputContractPolicy
from alphus.findings import Finding
from alphus.input_contracts import check_input_contracts, input_contract_findings

POLICY = InputContractPolicy(extensions=[".py"], exclude=[])


def analyze(source: str, policy: InputContractPolicy = POLICY) -> list[Finding]:
    return input_contract_findings(dedent(source).lstrip("\n"), policy)


@pytest.mark.parametrize(
    ("body", "interface"),
    [
        ("for value in values:\n  consume(value)", "Iterable[str]"),
        (
            "result = [value.upper() for value in values]\n return result",
            "Iterable[str]",
        ),
        ("return len(values)", "Sequence[str]"),
        ("return values[0]", "Sequence[str]"),
        (
            "for value in values:\n  consume(value)\n for value in values:\n  consume(value)",
            "Sequence[str]",
        ),
    ],
)
def test_sequence_advice_follows_visible_operations(body: str, interface: str) -> None:
    findings = analyze("def render(values: list[str]):\n " + body)

    assert len(findings) == 1
    assert findings[0].rule_id == "input-contracts.read-only-interface"
    assert interface in findings[0].message
    assert findings[0].severity == "warning"
    assert findings[0].line == 1


def test_imported_list_and_dict_aliases_are_resolved() -> None:
    findings = analyze("""
        from typing import Dict as D, List as L
        def render(values: L[str], lookup: D[str, int]):
            count = len(values)
            return lookup.get('size', count)
    """)

    assert [finding.rule_id for finding in findings] == [
        "input-contracts.read-only-interface",
        "input-contracts.read-only-interface",
    ]
    assert any("Sequence[str]" in finding.message for finding in findings)
    assert any("Mapping[str, int]" in finding.message for finding in findings)


def test_direct_alias_mutation_is_reported_at_the_write() -> None:
    findings = analyze("""
        def add(values: list[str]):
            alias = values
            alias.append('new')
    """)

    assert len(findings) == 1
    assert findings[0].rule_id == "input-contracts.argument-mutation"
    assert findings[0].line == 3
    assert "parameter values: append()" in findings[0].message
    assert "typed mutable contract" in findings[0].message


def test_item_deletion_and_augmented_assignment_preserve_typed_mutation() -> None:
    findings = analyze("""
        from collections.abc import MutableMapping
        def update(values: MutableMapping[str, int], items: list[str]):
            values['count'] = 1
            del values['old']
            items += ['new']
    """)

    assert [finding.line for finding in findings] == [3, 4, 5]
    assert {finding.rule_id for finding in findings} == {
        "input-contracts.argument-mutation"
    }


def test_mutation_through_a_reachable_value_does_not_claim_mapping_is_mutated() -> None:
    findings = analyze("""
        from collections.abc import Mapping
        def change(values: Mapping[str, list[str]]):
            nested = values['items']
            nested.append('new')
    """)

    assert len(findings) == 1
    assert findings[0].line == 4
    assert "value reached from this parameter" in findings[0].message
    assert "read-only interfaces are shallow" in findings[0].message


def test_rebinding_a_parameter_or_alias_is_not_mutating_the_caller() -> None:
    assert (
        analyze("""
        def change(values: list[str]):
            alias = values
            alias = []
            alias.append('local')
            values = []
            values.append('local')
    """)
        == []
    )


@pytest.mark.parametrize(
    "body",
    [
        "helper(values)",
        "return values",
        "copy = values.copy()",
        "for value in values:\n  consume(value)\n helper(values)",
        "if enabled:\n  alias = values\n else:\n  alias = []\n alias.append('maybe')",
        "def nested():\n  values.append('later')\n return len(values)",
    ],
)
def test_uncertain_escapes_and_branch_aliases_do_not_prove_read_only_use(
    body: str,
) -> None:
    assert analyze("def process(values: list[str]):\n " + body) == []


def test_list_specific_sort_is_an_observed_write_without_an_invalid_interface_fix() -> (
    None
):
    findings = analyze("def sort(values: list[str]):\n values.sort()")

    assert len(findings) == 1
    assert "sort()" in findings[0].message
    assert "MutableSequence" not in findings[0].message


def test_already_abstract_interfaces_are_allowed_and_mutability_stays_typed() -> None:
    assert (
        analyze(
            """
        from collections.abc import Iterable, Mapping, MutableSequence, Sequence
        def read(a: Iterable[str], b: Sequence[str], c: Mapping[str, int]):
            return len(b) + c.get('size', 0)
        def append(a: MutableSequence[str]):
            a.append('new')
    """,
            POLICY.model_copy(update={"report_mutation": False}),
        )
        == []
    )


def test_set_membership_can_use_an_abstract_set_contract() -> None:
    findings = analyze("def contains(values: set[str]):\n return 'x' in values")

    assert len(findings) == 1
    assert "AbstractSet[str]" in findings[0].message


def test_unknown_custom_annotations_and_variadic_element_annotations_are_not_inferred() -> (
    None
):
    assert (
        analyze("""
        from typing import TypeAlias
        Values: TypeAlias = list[str]
        def custom(values: Values):
            return len(values)
        def variadic(*values: list[str], **lookup: dict[str, int]):
            return len(values) + len(lookup)
    """)
        == []
    )


def test_policy_can_select_mutation_or_interface_advice_independently() -> None:
    source = "def read(values: list[str]):\n return len(values)"
    assert analyze(source, POLICY.model_copy(update={"suggest_read_only": False})) == []
    mutation = "def change(values: list[str]):\n values.append('x')"
    assert analyze(mutation, POLICY.model_copy(update={"report_mutation": False})) == []


def test_wrapper_uses_the_supplied_inventory_and_exclusions(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text("def read(x: list[str]):\n return len(x)\n")
    (tmp_path / "vendor.py").write_text("def read(x: list[str]):\n return len(x)\n")
    (tmp_path / "ignored.txt").write_text("this is not Python")
    policy = InputContractPolicy(extensions=[".py"], exclude=["vendor.py"])

    findings = check_input_contracts(
        tmp_path,
        iter([Path("vendor.py"), Path("source.py"), Path("ignored.txt")]),
        policy,
    )

    assert len(findings) == 1
    assert findings[0].path == "source.py"


def test_rebound_imported_type_names_are_not_treated_as_standard_collections() -> None:
    assert (
        analyze("""
        from typing import List as L
        L = CustomCollection
        def read(values: L[str]):
            return len(values)
    """)
        == []
    )


def test_annotated_collection_contracts_keep_their_element_types() -> None:
    findings = analyze("""
        from typing import Annotated, List as L
        def read(values: Annotated[L[str], 'label']):
            return len(values)
    """)
    assert len(findings) == 1
    assert "Sequence[str]" in findings[0].message


@pytest.mark.parametrize(
    "body",
    [
        "copy = values[:]\n copy.append('local')",
        "import arbitrary as values\n values.clear()",
        "def values():\n  pass\n values.clear()",
        "(values := [])\n values.append('local')",
        "with context() as values:\n  values.clear()",
        "return max(values, [])",
        "return sum([['x']], values)",
    ],
)
def test_copies_scalar_rebinding_and_rebound_names_do_not_claim_caller_mutation(
    body: str,
) -> None:
    assert analyze("def process(values: list[str]):\n " + body) == []


def test_visible_global_builtin_shadowing_suppresses_read_only_advice() -> None:
    assert (
        analyze("""
        def sum(values):
            values.append('x')
        def process(values: list[str]):
            return sum(values)
    """)
        == []
    )


def test_class_local_bindings_do_not_hide_a_later_caller_mutation() -> None:
    findings = analyze("""
        def process(values: list[str]):
            size = len(values)
            class Container:
                values = []
            values.append('caller')
    """)
    assert len(findings) == 1
    assert findings[0].rule_id == "input-contracts.argument-mutation"
    assert findings[0].line == 5


def test_unmodelled_try_and_match_bindings_do_not_prove_read_only_use() -> None:
    assert (
        analyze("""
        def process(values: list[str]):
            size = len(values)
            alias = values
            try:
                helper()
            except Exception:
                alias = []
            alias.append('maybe')
    """)
        == []
    )
    assert (
        analyze("""
        def process(values: list[str]):
            size = len(values)
            match event:
                case {'items': values}:
                    pass
            values.append('maybe')
    """)
        == []
    )


def test_rebinding_a_scalar_read_from_a_mapping_is_not_a_caller_write() -> None:
    assert (
        analyze("""
        def process(values: dict[str, int]):
            count = values['count']
            count += 1
    """)
        == []
    )
