"""Exercise local input contracts without claiming whole-program mutation proof."""

from pathlib import Path
from textwrap import dedent
from types import MappingProxyType

import pytest

from alphus.config import InputContractPolicy, load_config
from alphus.contracts.findings import Finding
from alphus.gates.review.input_contracts import (
    check_input_contracts,
    input_contract_findings,
)

POLICY = InputContractPolicy(extensions=[".py"], exclude=[])
DOMAIN_POLICY = InputContractPolicy(
    extensions=[".py"],
    exclude=[],
    domain_mapping_types=("app.models.EvaluationOptions",),
)
DECLARED_DOMAIN_BOUNDARY = MappingProxyType(
    {
        "path": "src/internal/evaluate.py",
        "function": "evaluate",
        "parameter": "packet",
        "domain_type": "app.models.EvaluationOptions",
    }
)
DOMAIN_BOUNDARY_POLICY = InputContractPolicy(
    extensions=[".py"],
    exclude=[],
    domain_mapping_contracts=(DECLARED_DOMAIN_BOUNDARY,),
)


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


def test_domain_union_and_imported_mapping_alias_with_literal_read_are_reviewed() -> (
    None
):
    findings = input_contract_findings(
        """from collections.abc import Mapping as M
from app.models import EvaluationOptions as Options
from app.json_types import JsonValue as JV
def evaluate(options: Options | M[str, JV]):
    return options["count"]
""",
        DOMAIN_POLICY,
        path="src/internal/evaluate.py",
    )

    assert len(findings) == 1
    assert (
        findings[0].rule_id
        == "alphus/python/none/correctness/generic-mapping-domain-escape"
    )
    assert findings[0].line == 4
    assert "app.models.EvaluationOptions" in findings[0].message
    assert "line(s) 5" in findings[0].message
    assert "does not prove validation is absent" in findings[0].message


def test_typing_union_dict_and_ignored_validation_result_remain_review_candidates() -> (
    None
):
    findings = input_contract_findings(
        """from typing import Union
from app.models import EvaluationOptions
def evaluate(options: Union[EvaluationOptions, dict[str, JsonValue]]):
    EvaluationOptions.model_validate(options)
    return options.get("count")
""",
        DOMAIN_POLICY,
    )
    assert len(findings) == 1
    assert "dict" in findings[0].message


def test_discarded_validator_inside_a_branch_is_not_normalization() -> None:
    findings = input_contract_findings(
        """from collections.abc import Mapping
from app.models import EvaluationOptions
def evaluate(options: EvaluationOptions | Mapping[str, JsonValue]):
    if isinstance(options, Mapping):
        EvaluationOptions.model_validate(options)
    return options["count"]
""",
        DOMAIN_POLICY,
    )

    assert len(findings) == 1
    assert "literal-key reads" in findings[0].message


def test_assigned_local_model_normalization_stops_direct_mapping_advice() -> None:
    assert (
        input_contract_findings(
            """from collections.abc import Mapping
from app.models import EvaluationOptions
def evaluate(options: EvaluationOptions | Mapping[str, JsonValue]):
    normalized = EvaluationOptions.model_validate(options)
    return _evaluate(normalized)
""",
            DOMAIN_POLICY,
        )
        == []
    )


def test_branch_specific_assigned_model_normalization_is_used() -> None:
    assert (
        input_contract_findings(
            """from collections.abc import Mapping
from app.models import EvaluationOptions
def evaluate(options: EvaluationOptions | Mapping[str, JsonValue]):
    if isinstance(options, Mapping):
        normalized = EvaluationOptions.model_validate(options)
        return _evaluate(normalized)
    return _evaluate(options)
""",
            DOMAIN_POLICY,
        )
        == []
    )


def test_declared_mapping_only_boundary_requires_literal_mapping_reads() -> None:
    findings = input_contract_findings(
        """from collections.abc import Mapping
from app.json_types import JsonValue
def evaluate(packet: Mapping[str, JsonValue]):
    return packet["state"]
""",
        DOMAIN_BOUNDARY_POLICY,
        path="src/internal/evaluate.py",
    )

    assert len(findings) == 1
    assert findings[0].rule_id == (
        "alphus/python/none/correctness/generic-mapping-domain-escape"
    )
    assert "expects app.models.EvaluationOptions" in findings[0].message
    assert "literal-key reads at line(s) 4" in findings[0].message


def test_mapping_escape_evidence_follows_one_direct_local_helper_pass() -> None:
    findings = input_contract_findings(
        """from collections.abc import Mapping
from app.json_types import JsonValue
def evaluate(packet: Mapping[str, JsonValue]):
    return _read_state(packet)
def _read_state(payload):
    return payload["state"]
""",
        DOMAIN_BOUNDARY_POLICY,
        path="src/internal/evaluate.py",
    )
    assert len(findings) == 1
    assert "direct helper pass-through at line 4 to _read_state" in findings[0].message
    assert "reads 6" in findings[0].message


def test_mapping_escape_cross_function_following_accepts_linear_aliases_but_not_ambiguity() -> (
    None
):
    alias_case = """from collections.abc import Mapping
from app.json_types import JsonValue
def evaluate(packet: Mapping[str, JsonValue]):
    local = packet
    return _read(local)
def _read(value):
    local = value
    return local["state"]
"""
    ambiguous_case = """from collections.abc import Mapping
from app.json_types import JsonValue
def evaluate(packet: Mapping[str, JsonValue]):
    return _read(packet)
def _read(value):
    return value["state"]
def _read(other):
    return other["state"]
"""
    findings = input_contract_findings(
        alias_case, DOMAIN_BOUNDARY_POLICY, path="src/internal/evaluate.py"
    )
    assert len(findings) == 1
    assert "direct helper pass-through at line 5 to _read" in findings[0].message
    assert "reads 8" in findings[0].message
    assert (
        input_contract_findings(
            ambiguous_case, DOMAIN_BOUNDARY_POLICY, path="src/internal/evaluate.py"
        )
        == []
    )


def test_shadowed_domain_import_alias_remains_unresolved() -> None:
    source = """from collections.abc import Mapping as M
from typing import Union as Either
from app.models import EvaluationOptions as Options
from app.json_types import JsonValue as JV
Options = object
def evaluate(options: Either[Options, M[str, JV]]):
    return options["state"]
"""

    assert input_contract_findings(source, DOMAIN_POLICY) == []


def test_unresolved_model_identity_does_not_match_configured_domain_contract() -> None:
    source = """from collections.abc import Mapping
def evaluate(options: EvaluationOptions | Mapping[str, JsonValue]):
    return options["state"]
"""

    assert input_contract_findings(source, DOMAIN_POLICY) == []


@pytest.mark.parametrize(
    ("source", "path", "policy"),
    [
        (
            """from collections.abc import Mapping
def evaluate(packet: Mapping[str, JsonValue]):
    return packet["state"]
""",
            "src/internal/other.py",
            DOMAIN_BOUNDARY_POLICY,
        ),
        (
            """from collections.abc import Mapping
def evaluate(packet: Mapping[str, object]):
    return packet["state"]
""",
            "src/internal/evaluate.py",
            DOMAIN_BOUNDARY_POLICY,
        ),
        (
            """from collections.abc import Mapping
def evaluate(packet: Mapping[str, JsonValue]):
    return len(packet)
""",
            "src/internal/evaluate.py",
            DOMAIN_BOUNDARY_POLICY,
        ),
        (
            """from collections.abc import Mapping
def evaluate(packet: Mapping[str, JsonValue]):
    return packet["state"]
""",
            "src/internal/evaluate.py",
            InputContractPolicy(extensions=[".py"], exclude=[]),
        ),
    ],
)
def test_mapping_only_candidate_requires_exact_consumer_scope_and_shape(
    source: str, path: str, policy: InputContractPolicy
) -> None:
    assert input_contract_findings(source, policy, path=path) == []


def test_declared_object_boundary_reports_direct_required_attribute_reads() -> None:
    policy = InputContractPolicy(
        extensions=[".py"],
        exclude=[],
        domain_mapping_contracts=(
            {
                **DECLARED_DOMAIN_BOUNDARY,
                "function": "Evaluator.evaluate",
            },
        ),
    )
    findings = input_contract_findings(
        """class Evaluator:
    def evaluate(self, packet: object):
        return packet.frame
""",
        policy,
        path="src/internal/evaluate.py",
    )

    assert len(findings) == 1
    assert (
        findings[0].rule_id
        == "alphus/python/none/correctness/broad-object-domain-input"
    )
    assert "expects app.models.EvaluationOptions" in findings[0].message
    assert ".frame at line 3" in findings[0].message


def test_object_attribute_review_requires_declared_contract_and_direct_read() -> None:
    source = "def evaluate(packet: object):\n    return packet.frame\n"
    assert input_contract_findings(source, DOMAIN_BOUNDARY_POLICY) == []
    policy = InputContractPolicy(
        extensions=[".py"],
        exclude=[],
        domain_mapping_contracts=(DECLARED_DOMAIN_BOUNDARY,),
    )
    assert (
        input_contract_findings(
            "def evaluate(packet: object):\n    return repr(packet)\n",
            policy,
            path="src/internal/evaluate.py",
        )
        == []
    )


def test_domain_mapping_contract_selectors_must_be_unique_and_relative() -> None:
    with pytest.raises(ValueError, match="selectors must be unique"):
        InputContractPolicy(
            extensions=[".py"],
            exclude=[],
            domain_mapping_contracts=(
                DECLARED_DOMAIN_BOUNDARY,
                DECLARED_DOMAIN_BOUNDARY,
            ),
        )
    with pytest.raises(ValueError, match="relative POSIX path"):
        InputContractPolicy(
            extensions=[".py"],
            exclude=[],
            domain_mapping_contracts=(
                {**DECLARED_DOMAIN_BOUNDARY, "path": "../evaluate.py"},
            ),
        )


@pytest.mark.parametrize(
    "body",
    [
        "options = {}\n return options['count']",
        "def nested():\n  return options['count']\n return None",
        (
            "if isinstance(options, dict):\n"
            "  normalized = EvaluationOptions.model_validate(options)\n"
            "  return _evaluate(normalized)\n"
            " return _evaluate(options)"
        ),
    ],
)
def test_rebinding_nested_and_branch_validation_stay_uncertain(body: str) -> None:
    source = (
        "from collections.abc import Mapping\n"
        "from app.models import EvaluationOptions\n"
        "def evaluate(options: EvaluationOptions | Mapping[str, JsonValue]):\n " + body
    )
    assert input_contract_findings(source, DOMAIN_POLICY) == []


def test_sample_domain_profile_selects_existing_input_contract_rule() -> None:
    config = load_config(Path("examples/consumer/domain-mapping-review.toml"))
    plan = config.orchestration.resolve_profile("domain-review")
    assert plan is not None
    assert plan.steps == ("Domain mapping review",)


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
