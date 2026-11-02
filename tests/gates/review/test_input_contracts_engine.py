"""Exercise local input contracts without claiming whole-program mutation proof."""

from pathlib import Path
from textwrap import dedent
from types import MappingProxyType

import pytest

from alphus.config import InputContractPolicy
from alphus.contracts.findings import Finding
from alphus.gates.review.input_contracts import (
    check_input_contracts,
    input_contract_findings,
)

POLICY = InputContractPolicy(extensions=[".py"], exclude=[])


def analyze(source: str, policy: InputContractPolicy = POLICY) -> list[Finding]:
    return input_contract_findings(dedent(source).lstrip("\n"), policy)


MANUAL_SCHEMA_BOUNDARY = MappingProxyType(
    {
        "path": "src/decode.py",
        "function": "parse_options",
        "parameter": "payload",
        "authoritative_schema": "app.models.Options",
    }
)


def manual_schema_findings(source: str, **contract_updates: object) -> list[Finding]:
    policy = InputContractPolicy(
        extensions=[".py"],
        exclude=[],
        manual_schema_validation_boundaries=[
            {**MANUAL_SCHEMA_BOUNDARY, **contract_updates}
        ],
    )
    return input_contract_findings(
        dedent(source).lstrip("\n"), policy, path="src/decode.py"
    )


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
    assert (
        findings[0].rule_id
        == "alphus/python/none/correctness/read-only-interface-violation"
    )
    assert interface in findings[0].message
    assert findings[0].severity == "warning"
    assert findings[0].line == 1


def test_abstract_sequence_advice_is_opt_in_by_path(tmp_path: Path) -> None:
    relative = Path("src/read.py")
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text(
        "from collections.abc import Sequence\n"
        "def read(values: Sequence[str]):\n"
        "    for value in values:\n"
        "        consume(value)\n",
        encoding="utf-8",
    )

    assert check_input_contracts(tmp_path, [relative], POLICY) == []

    scoped = POLICY.model_copy(update={"sequence_narrowing_paths": ["src/read.py"]})
    findings = check_input_contracts(tmp_path, [relative], scoped)

    assert len(findings) == 1
    assert "Iterable[str]" in findings[0].message
    assert "declared Sequence[str]" in findings[0].message


def test_imported_list_and_dict_aliases_are_resolved() -> None:
    findings = analyze("""
        from typing import Dict as D, List as L
        def render(values: L[str], lookup: D[str, int]):
            count = len(values)
            return lookup.get('size', count)
    """)

    assert [finding.rule_id for finding in findings] == [
        "alphus/python/none/correctness/read-only-interface-violation",
        "alphus/python/none/correctness/read-only-interface-violation",
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
    assert findings[0].rule_id == "alphus/python/none/correctness/argument-mutation"
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
        "alphus/python/none/correctness/argument-mutation"
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


def test_binary_buffers_report_writes_without_replacement_type_advice() -> None:
    findings = analyze("""
        def update(data: bytearray, view: memoryview, fixed: bytes):
            data.append(1)
            view[0] = 2
            return len(fixed)
    """)

    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/none/correctness/argument-mutation", 2),
        ("alphus/python/none/correctness/argument-mutation", 3),
    ]
    assert analyze("def inspect(data: bytearray):\n return len(data)\n") == []


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
    assert findings[0].rule_id == "alphus/python/none/correctness/argument-mutation"
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


def test_manual_schema_advisory_groups_repeated_selected_boundary_checks() -> None:
    findings = manual_schema_findings("""
        def parse_options(payload):
            if "kind" not in payload:
                raise ValueError("missing kind")
            if not isinstance(payload.get("kind"), str):
                raise ValueError("invalid kind")
            if not isinstance(payload.get("limit"), int):
                raise ValueError("invalid limit")
            if payload.get("limit") < 0:
                raise ValueError("negative limit")
            return payload
    """)

    assert len(findings) == 1
    assert (
        findings[0].rule_id == "alphus/python/none/correctness/manual-schema-validation"
    )
    assert findings[0].line == 1
    assert findings[0].severity == "info"
    assert "app.models.Options" in findings[0].message
    assert "fixed-key checks" in findings[0].message
    assert "kind is str" in findings[0].message
    assert "limit is int" in findings[0].message
    assert "numeric range" in findings[0].message
    assert "does not prove a validation defect" in findings[0].message


def test_manual_schema_selector_does_not_treat_a_global_as_an_input_parameter() -> None:
    findings = manual_schema_findings("""
        def parse_options():
            if "kind" not in payload:
                raise ValueError("missing kind")
            if not isinstance(payload.get("kind"), str):
                raise ValueError("invalid kind")
            if not isinstance(payload.get("limit"), int):
                raise ValueError("invalid limit")
            if payload.get("limit") < 0:
                raise ValueError("negative limit")
            return payload
    """)

    assert len(findings) == 1
    assert "not evaluated" in findings[0].message
    assert "does not declare 'payload' as an input parameter" in findings[0].message
    assert "fixed-key checks" not in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        """
        def parse_options(payload):
            if not isinstance(payload.get("kind"), str):
                raise ValueError("invalid kind")
        """,
        """
        def parse_options(payload):
            for key, value in payload.items():
                if not isinstance(key, str):
                    raise ValueError("invalid JSON key")
            return payload
        """,
        """
        def parse_options(payload):
            return Options.model_validate(payload)
        """,
        """
        def parse_options(payload):
            parsed = TypeAdapter(Options).validate_python(payload)
            return parsed
        """,
        """
        def parse_options(payload):
            raw = payload
            if "kind" not in raw:
                raise ValueError("missing kind")
            if not isinstance(raw.get("kind"), str):
                raise ValueError("invalid kind")
            if not isinstance(raw.get("limit"), int):
                raise ValueError("invalid limit")
            if raw.get("limit") < 0:
                raise ValueError("negative limit")
            return raw
        """,
        """
        def parse_options(payload):
            payload = {"kind": "open"}
            if "kind" not in payload:
                raise ValueError("missing kind")
            if not isinstance(payload.get("kind"), str):
                raise ValueError("invalid kind")
            if not isinstance(payload.get("limit"), int):
                raise ValueError("invalid limit")
            if payload.get("limit") < 0:
                raise ValueError("negative limit")
            return payload
        """,
        """
        def parse_options(payload):
            def inspect(payload):
                if "kind" not in payload:
                    raise ValueError("missing kind")
                if not isinstance(payload.get("kind"), str):
                    raise ValueError("invalid kind")
                if not isinstance(payload.get("limit"), int):
                    raise ValueError("invalid limit")
                if payload.get("limit") < 0:
                    raise ValueError("negative limit")
            return payload
        """,
        """
        def parse_options(payload):
            extensions = payload.get("extensions", {})
            return {key: value for key, value in extensions.items()}
        """,
    ],
)
def test_manual_schema_advisory_accepts_guards_walkers_validators_and_alias_limits(
    source: str,
) -> None:
    assert manual_schema_findings(source) == []


def test_manual_schema_advisory_records_unknown_helpers_as_uncertainty() -> None:
    findings = manual_schema_findings("""
        def parse_options(payload):
            if "kind" not in payload:
                raise ValueError("missing kind")
            if not isinstance(payload.get("kind"), str):
                raise ValueError("invalid kind")
            if not isinstance(payload.get("limit"), int):
                raise ValueError("invalid limit")
            if payload.get("limit") < 0:
                raise ValueError("negative limit")
            return inspect_unknown_schema(payload)
    """)

    assert len(findings) == 1
    assert "unresolved" in findings[0].message
    assert "does not prove a validation defect" in findings[0].message


def test_manual_schema_advisory_accepts_declared_custom_validator_flow() -> None:
    findings = manual_schema_findings(
        """
        def parse_options(payload):
            parsed = app.validate_payload(payload)
            return parsed
        """,
        validator="app.validate_payload",
    )

    assert findings == []


@pytest.mark.parametrize(
    ("validator", "call"),
    [
        (
            "TypeAdapter.validate_python",
            "TypeAdapter(Options).validate_python(payload)",
        ),
        ("Options.model_validate", "Options.model_validate(payload)"),
        ("app.validate_payload", "app.validate_payload(payload=payload)"),
    ],
)
def test_manual_schema_advisory_accepts_configured_and_factory_validators(
    validator: str, call: str
) -> None:
    findings = manual_schema_findings(
        f"""
        def parse_options(payload):
            if "kind" not in payload:
                raise ValueError("missing kind")
            if not isinstance(payload.get("kind"), str):
                raise ValueError("invalid kind")
            if not isinstance(payload.get("limit"), int):
                raise ValueError("invalid limit")
            if payload.get("limit") < 0:
                raise ValueError("negative limit")
            parsed = {call}
            return parsed
        """,
        validator=validator,
    )

    assert findings == []


def test_manual_schema_advisory_keeps_branch_completeness_unknown() -> None:
    findings = manual_schema_findings("""
        def parse_options(payload):
            if payload.get("enabled"):
                if "kind" not in payload:
                    raise ValueError("missing kind")
                if not isinstance(payload.get("kind"), str):
                    raise ValueError("invalid kind")
                if not isinstance(payload.get("limit"), int):
                    raise ValueError("invalid limit")
                if payload.get("limit") < 0:
                    raise ValueError("negative limit")
            return payload
    """)

    assert len(findings) == 1
    assert "branch completeness remain unresolved" in findings[0].message


def test_manual_schema_advisory_is_opt_in_and_respects_excluded_paths(
    tmp_path: Path,
) -> None:
    relative = Path("src/decode.py")
    source = (
        "def parse_options(payload):\n"
        "    if 'kind' not in payload: raise ValueError()\n"
        "    if not isinstance(payload.get('kind'), str): raise ValueError()\n"
        "    if not isinstance(payload.get('limit'), int): raise ValueError()\n"
        "    if payload.get('limit') < 0: raise ValueError()\n"
    )
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding="utf-8")
    policy = InputContractPolicy(
        extensions=[".py"],
        exclude=["src/decode.py"],
        manual_schema_validation_boundaries=[MANUAL_SCHEMA_BOUNDARY],
    )

    assert input_contract_findings(source, POLICY, path=relative.as_posix()) == []
    assert check_input_contracts(tmp_path, [relative], policy) == []


def test_manual_schema_contracts_validate_identity_and_custom_review_reasons() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        InputContractPolicy(
            extensions=[".py"],
            exclude=[],
            manual_schema_validation_boundaries=[
                MANUAL_SCHEMA_BOUNDARY,
                MANUAL_SCHEMA_BOUNDARY,
            ],
        )
    with pytest.raises(ValueError, match="must explain the contract"):
        manual_schema_findings(
            "def parse_options(payload): pass", justification="custom"
        )
