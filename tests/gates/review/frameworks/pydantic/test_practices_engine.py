"""Synthetic Pydantic source contracts for optional review findings."""

import pytest
from pydantic import BaseModel, ValidationError

from alphus.config import PydanticPracticePolicy
from alphus.gates.review.frameworks.pydantic.practices import pydantic_practice_findings


def _policy(**options: bool | tuple[str, ...]) -> PydanticPracticePolicy:
    return PydanticPracticePolicy.model_validate({"extensions": (".py",), **options})


def test_dump_revalidation_follows_local_aliases_and_reports_source_line() -> None:
    source = (
        "def output(model):\n"
        "    data = model.model_dump(mode='json')\n"
        "    alias = data\n"
        "    return Adapter.model_validate(alias)\n"
    )
    findings = pydantic_practice_findings(source, _policy(), path="src/output.py")

    assert [
        (item.rule_id, item.path, item.line, item.severity) for item in findings
    ] == [
        (
            "alphus/python/pydantic/validation/dump-revalidation",
            "src/output.py",
            4,
            "warning",
        )
    ]


def test_dump_revalidation_detects_inline_json_and_skips_plain_validation() -> None:
    source = (
        "def output(model, raw):\n"
        "    first = Adapter.validate_json(model.model_dump_json())\n"
        "    second = Adapter.validate_python(raw)\n"
        "    return model.model_dump(mode='json')\n"
    )
    findings = pydantic_practice_findings(source, _policy())

    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/pydantic/validation/dump-revalidation", 2)
    ]


def test_declared_domain_return_contract_reviews_direct_model_dump() -> None:
    source = (
        "from app.models import Summary as Result\n"
        "def build_summary(summary: Result) -> Result:\n"
        "    return summary.model_dump()\n"
        "def write_json(summary: Result) -> dict[str, object]:\n"
        "    return summary.model_dump()\n"
    )
    policy = PydanticPracticePolicy.model_validate(
        {
            "extensions": [".py"],
            "external_model_names": ["Summary"],
            "domain_return_contracts": [
                {
                    "path": "src/domain.py",
                    "function": "build_summary",
                    "model": "app.models.Summary",
                }
            ],
        }
    )

    findings = pydantic_practice_findings(source, policy, path="src/domain.py")

    assert [
        (item.rule_id, item.line, item.severity, item.path) for item in findings
    ] == [
        (
            "alphus/python/pydantic/correctness/model-dump-domain-return",
            3,
            "info",
            "src/domain.py",
        )
    ]
    assert "does not prove the conversion is unsafe" in findings[0].message


def test_domain_return_contract_requires_declared_identity_and_exact_scope() -> None:
    source = (
        "from app.models import Summary\n"
        "def build_summary(summary: Summary) -> Summary:\n"
        "    return summary.model_dump()\n"
    )
    policy = PydanticPracticePolicy.model_validate(
        {
            "extensions": [".py"],
            "external_model_names": ["OtherSummary"],
            "domain_return_contracts": [
                {
                    "path": "src/domain.py",
                    "function": "build_summary",
                    "model": "app.models.OtherSummary",
                }
            ],
        }
    )

    assert pydantic_practice_findings(source, policy, path="src/domain.py") == []
    assert pydantic_practice_findings(source, policy, path="src/io.py") == []


def test_domain_return_contracts_reject_duplicate_selectors() -> None:
    contract = {
        "path": "src/domain.py",
        "function": "build_summary",
        "model": "app.models.Summary",
    }
    with pytest.raises(ValueError, match="selectors must be unique"):
        PydanticPracticePolicy.model_validate(
            {
                "extensions": [".py"],
                "domain_return_contracts": [contract, contract],
            }
        )


def test_declared_finite_state_contract_reports_complete_raw_string_chain() -> None:
    source = (
        "def dispatch(action: str):\n"
        "    if action == 'approve':\n"
        "        return accept()\n"
        "    elif 'reject' == action:\n"
        "        return deny()\n"
    )
    contract = {
        "path": "src/actions.py",
        "function": "dispatch",
        "parameter": "action",
        "values": ["approve", "reject"],
    }
    policy = _policy(finite_state_contracts=(contract,))

    assert pydantic_practice_findings(source, _policy()) == []
    findings = pydantic_practice_findings(source, policy, path="src/actions.py")

    assert [(item.rule_id, item.line, item.severity) for item in findings] == [
        (
            "alphus/python/pydantic/style/finite-state-string-selector",
            4,
            "info",
        )
    ]
    assert "does not infer a domain from repeated literals" in findings[0].message


def test_finite_state_contract_does_not_collect_nested_compound_comparisons() -> None:
    source = (
        "def dispatch(action: str, enabled: bool):\n"
        "    if enabled and action == 'approve':\n"
        "        return accept()\n"
        "    elif enabled and action == 'reject':\n"
        "        return deny()\n"
    )
    policy = _policy(
        finite_state_contracts=(
            {
                "path": "src/actions.py",
                "function": "dispatch",
                "parameter": "action",
                "values": ["approve", "reject"],
            },
        )
    )

    assert pydantic_practice_findings(source, policy, path="src/actions.py") == []


def test_finite_state_contract_skips_typed_partial_rebound_and_unselected_inputs() -> (
    None
):
    source = (
        "from typing import Literal\n"
        "def typed(action: Literal['approve', 'reject']):\n"
        "    if action == 'approve': return accept()\n"
        "    elif action == 'reject': return deny()\n"
        "def partial(action: str):\n"
        "    if action == 'approve': return accept()\n"
        "def rebound(action: str):\n"
        "    action = normalize(action)\n"
        "    if action == 'approve': return accept()\n"
        "    elif action == 'reject': return deny()\n"
        "str = ProtocolString\n"
        "def shadowed(action: str):\n"
        "    if action == 'approve': return accept()\n"
        "    elif action == 'reject': return deny()\n"
        "StateKey = str\n"
        "def aliased(action: StateKey):\n"
        "    if action == 'approve': return accept()\n"
        "    elif action == 'reject': return deny()\n"
        "def open_input(action: str):\n"
        "    if action == 'approve': return accept()\n"
        "    elif action == 'reject': return deny()\n"
    )
    policy = _policy(
        finite_state_contracts=(
            {
                "path": "src/actions.py",
                "function": "typed",
                "parameter": "action",
                "values": ["approve", "reject"],
            },
            {
                "path": "src/actions.py",
                "function": "partial",
                "parameter": "action",
                "values": ["approve", "reject"],
            },
            {
                "path": "src/actions.py",
                "function": "rebound",
                "parameter": "action",
                "values": ["approve", "reject"],
            },
            {
                "path": "src/actions.py",
                "function": "shadowed",
                "parameter": "action",
                "values": ["approve", "reject"],
            },
            {
                "path": "src/actions.py",
                "function": "aliased",
                "parameter": "action",
                "values": ["approve", "reject"],
            },
            {
                "path": "src/other.py",
                "function": "open_input",
                "parameter": "action",
                "values": ["approve", "reject"],
            },
        )
    )

    assert pydantic_practice_findings(source, policy, path="src/actions.py") == []


def test_finite_state_contract_rejects_duplicate_values() -> None:
    with pytest.raises(ValueError, match="finite-state values must be unique"):
        _policy(
            finite_state_contracts=(
                {
                    "path": "src/actions.py",
                    "function": "dispatch",
                    "parameter": "action",
                    "values": ["approve", "approve"],
                },
            )
        )


def test_finite_state_contracts_reject_duplicate_selectors() -> None:
    contract = {
        "path": "src/actions.py",
        "function": "dispatch",
        "parameter": "action",
        "values": ["approve", "reject"],
    }
    with pytest.raises(ValueError, match="finite-state selectors must be unique"):
        _policy(finite_state_contracts=(contract, contract))


def test_utc_persistence_contract_reports_only_known_non_utc_capture() -> None:
    source = (
        "from datetime import datetime, timezone\n"
        "from zoneinfo import ZoneInfo\n"
        "def save_local(writer):\n"
        "    writer.save(created_at=datetime.now(ZoneInfo('Europe/Paris')))\n"
        "def save_utc(writer):\n"
        "    writer.save(created_at=datetime.now(timezone.utc))\n"
        "def save_unknown(writer, zone):\n"
        "    writer.save(created_at=datetime.now(zone))\n"
    )
    contract = {
        "path": "src/storage.py",
        "function": "save_local",
        "call": "writer.save",
        "keyword": "created_at",
    }
    policy = _policy(utc_persistence_contracts=(contract,))

    findings = pydantic_practice_findings(source, policy, path="src/storage.py")

    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/pydantic/correctness/non-utc-persistence", 4)
    ]
    assert pydantic_practice_findings(source, policy, path="src/other.py") == []


def test_utc_persistence_accepts_zero_offset_etc_gmt_zone() -> None:
    source = (
        "from datetime import datetime\n"
        "from zoneinfo import ZoneInfo\n"
        "def save_created_at(writer):\n"
        "    writer.save(created_at=datetime.now(ZoneInfo('Etc/GMT')))\n"
    )
    policy = _policy(
        utc_persistence_contracts=(
            {
                "path": "src/storage.py",
                "function": "save_created_at",
                "call": "writer.save",
                "keyword": "created_at",
            },
        )
    )

    assert pydantic_practice_findings(source, policy, path="src/storage.py") == []


@pytest.mark.parametrize("zone", ("Etc/UCT", "Etc/Greenwich", "GMT+0", "GMT-0"))
def test_utc_persistence_accepts_additional_zero_offset_zone_aliases(zone: str) -> None:
    source = (
        "from datetime import datetime\n"
        "from zoneinfo import ZoneInfo\n"
        "def save_created_at(writer):\n"
        f"    writer.save(created_at=datetime.now(ZoneInfo({zone!r})))\n"
    )
    policy = _policy(
        utc_persistence_contracts=(
            {
                "path": "src/storage.py",
                "function": "save_created_at",
                "call": "writer.save",
                "keyword": "created_at",
            },
        )
    )

    assert pydantic_practice_findings(source, policy, path="src/storage.py") == []


def test_utc_persistence_requires_explicit_utc_normalization() -> None:
    source = (
        "from datetime import datetime, timezone\n"
        "from zoneinfo import ZoneInfo\n"
        "def save_created_at(writer):\n"
        "    writer.save(created_at=datetime.now(ZoneInfo('Europe/Paris'))"
        ".astimezone(timezone.utc))\n"
        "    writer.save(created_at=datetime.now(ZoneInfo('Europe/Paris'))"
        ".astimezone(ZoneInfo('America/Los_Angeles')))\n"
        "    writer.save(created_at=datetime.now(ZoneInfo('Europe/Paris'))"
        ".astimezone())\n"
        "    writer.save(created_at=datetime.now(ZoneInfo('Europe/Paris'))"
        ".replace(tzinfo=timezone.utc))\n"
    )
    policy = _policy(
        utc_persistence_contracts=(
            {
                "path": "src/storage.py",
                "function": "save_created_at",
                "call": "writer.save",
                "keyword": "created_at",
            },
        )
    )

    findings = pydantic_practice_findings(source, policy, path="src/storage.py")

    assert [(item.line, item.rule_id) for item in findings] == [
        (5, "alphus/python/pydantic/correctness/non-utc-persistence"),
        (6, "alphus/python/pydantic/correctness/non-utc-persistence"),
        (7, "alphus/python/pydantic/correctness/non-utc-persistence"),
    ]


def test_utc_persistence_accepts_imported_utc_and_checks_final_conversion() -> None:
    source = (
        "from datetime import UTC, datetime, timezone\n"
        "from zoneinfo import ZoneInfo\n"
        "def save_created_at(writer):\n"
        "    writer.save(created_at=datetime.now(ZoneInfo('Europe/Paris'))"
        ".astimezone(UTC))\n"
        "    writer.save(created_at=datetime.now(ZoneInfo('Europe/Paris'))"
        ".astimezone(timezone.utc).astimezone(ZoneInfo('Europe/Paris')))\n"
    )
    policy = _policy(
        utc_persistence_contracts=(
            {
                "path": "src/storage.py",
                "function": "save_created_at",
                "call": "writer.save",
                "keyword": "created_at",
            },
        )
    )

    findings = pydantic_practice_findings(source, policy, path="src/storage.py")

    assert [(item.line, item.rule_id) for item in findings] == [
        (5, "alphus/python/pydantic/correctness/non-utc-persistence")
    ]


def test_utc_persistence_ignores_nested_function_outside_selected_boundary() -> None:
    source = (
        "from datetime import datetime\n"
        "from zoneinfo import ZoneInfo\n"
        "def save_created_at(writer):\n"
        "    def local_example():\n"
        "        writer.save(created_at=datetime.now(ZoneInfo('Europe/Paris')))\n"
        "    return None\n"
    )
    policy = _policy(
        utc_persistence_contracts=(
            {
                "path": "src/storage.py",
                "function": "save_created_at",
                "call": "writer.save",
                "keyword": "created_at",
            },
        )
    )

    assert pydantic_practice_findings(source, policy, path="src/storage.py") == []


def test_rebinding_and_nested_functions_do_not_carry_dump_state() -> None:
    source = (
        "def output(model, raw):\n"
        "    data = model.model_dump()\n"
        "    data = raw\n"
        "    def nested():\n"
        "        return Adapter.model_validate(data)\n"
        "    return Adapter.model_validate(data)\n"
    )
    assert pydantic_practice_findings(source, _policy()) == []


def test_explicit_mutability_is_opt_in_and_handles_pydantic_aliases() -> None:
    source = (
        "from pydantic import BaseModel as Model, ConfigDict as Config\n"
        "class Parent(Model):\n"
        "    model_config = Config(frozen=True)\n"
        "class Child(Parent):\n"
        "    value: int\n"
        "class Mutable(Model, frozen=False):\n"
        "    value: int\n"
        "class Recorded(Model):\n"
        "    model_config = {'frozen': False}\n"
        "class Other:\n"
        "    value: int\n"
    )
    assert pydantic_practice_findings(source, _policy()) == []
    findings = pydantic_practice_findings(source, _policy(require_explicit_frozen=True))
    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/pydantic/correctness/implicit-mutability", 4)
    ]


def test_model_dump_review_can_be_disabled_independently() -> None:
    source = "def output(model):\n return Model.model_validate(model.model_dump())\n"
    assert (
        pydantic_practice_findings(source, _policy(report_dump_revalidation=False))
        == []
    )


def test_unvalidated_construct_and_copy_update_resolve_local_models() -> None:
    source = (
        "from pydantic import BaseModel as Model\n"
        "class Item(Model):\n"
        "    value: int\n"
        "def update(item: Item, raw: object):\n"
        "    constructed = Item.model_construct(value=raw)\n"
        "    copied = item.model_copy(update={'value': raw})\n"
        "    unchanged = item.model_copy()\n"
        "    ignored = object.model_construct()\n"
    )
    findings = pydantic_practice_findings(
        source,
        _policy(
            report_unvalidated_construct=True,
            report_unvalidated_copy_update=True,
        ),
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/pydantic/validation/unvalidated-construct", 5),
        ("alphus/python/pydantic/validation/unvalidated-copy-update", 6),
    ]


def test_pydantic_rules_are_independent_and_ignore_unknown_receivers() -> None:
    source = (
        "from pydantic import BaseModel, Field, validator\n"
        "class Item(BaseModel):\n"
        "    value: int = Field(0)\n"
        "    @validator('value')\n"
        "    def check_value(cls, value):\n"
        "        return value\n"
        "def update(item: Item, raw: object):\n"
        "    Item.model_construct(value=raw)\n"
        "    item.model_copy(update={'value': raw})\n"
        "    item.dict()\n"
        "    unrelated.model_construct()\n"
    )

    findings = pydantic_practice_findings(
        source, _policy(report_unvalidated_construct=True)
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/pydantic/validation/unvalidated-construct", 8)
    ]


def test_model_methods_follow_simple_aliases_and_shadowing() -> None:
    source = (
        "from pydantic import BaseModel as Model\n"
        "class Item(Model):\n"
        "    def legacy_instance_method(self):\n"
        "        return self.dict()\n"
        "    @classmethod\n"
        "    def legacy_class_method(cls):\n"
        "        return cls.parse_obj({})\n"
        "class UnresolvedChild(UnknownBase):\n"
        "    pass\n"
        "def update(item: Item, raw: object):\n"
        "    alias = item\n"
        "    alias.model_copy(update={'value': raw})\n"
        "    alias = object()\n"
        "    alias.model_copy(update={'value': raw})\n"
        "    unrelated.model_construct()\n"
        "    def nested(unrelated):\n"
        "        unrelated.dict()\n"
        "        unrelated.model_construct()\n"
        "def unresolved(item: UnresolvedChild):\n"
        "    item.model_construct()\n"
    )

    findings = pydantic_practice_findings(
        source,
        _policy(
            report_deprecated_v1_apis=True,
            report_unvalidated_copy_update=True,
        ),
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/pydantic/correctness/deprecated-v1-api", 4),
        ("alphus/python/pydantic/correctness/deprecated-v1-api", 7),
        ("alphus/python/pydantic/validation/unvalidated-copy-update", 12),
    ]


def test_module_rebinding_does_not_preserve_a_pydantic_class_identity() -> None:
    source = (
        "from pydantic import BaseModel\n"
        "class Item(BaseModel):\n"
        "    value: int\n"
        "Item = object()\n"
        "Item.model_construct()\n"
    )

    assert (
        pydantic_practice_findings(source, _policy(report_unvalidated_construct=True))
        == []
    )


def test_deprecated_v1_apis_resolve_aliases_and_model_methods() -> None:
    source = (
        "from pydantic import BaseModel, validator as validate, parse_obj_as as parse\n"
        "class Item(BaseModel):\n"
        "    value: int\n"
        "    class Config:\n"
        "        orm_mode = True\n"
        "    @validate('value')\n"
        "    def check_value(cls, value):\n"
        "        return value\n"
        "def parse_value(item: Item):\n"
        "    item.dict()\n"
        "    return parse(Item, {})\n"
    )
    findings = pydantic_practice_findings(
        source, _policy(report_deprecated_v1_apis=True)
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/pydantic/correctness/deprecated-v1-api", 4),
        ("alphus/python/pydantic/correctness/deprecated-v1-api", 6),
        ("alphus/python/pydantic/correctness/deprecated-v1-api", 10),
        ("alphus/python/pydantic/correctness/deprecated-v1-api", 11),
    ]


def test_validator_fallthrough_reports_missing_return_but_skips_complete_and_complex() -> (
    None
):
    source = (
        "from pydantic import BaseModel, field_validator as validate\n"
        "class Item(BaseModel):\n"
        "    value: int\n"
        "    @validate('value', mode='before')\n"
        "    @classmethod\n"
        "    def incomplete(cls, value):\n"
        "        if value < 0:\n"
        "            raise ValueError()\n"
        "    @validate('value', mode='after')\n"
        "    @classmethod\n"
        "    def complete(cls, value):\n"
        "        if value < 0:\n"
        "            raise ValueError()\n"
        "        return value\n"
        "    @validate('value', mode='wrap')\n"
        "    @classmethod\n"
        "    def uncertain(cls, value, handler):\n"
        "        try:\n"
        "            return handler(value)\n"
        "        except ValueError:\n"
        "            raise\n"
    )
    findings = pydantic_practice_findings(
        source, _policy(report_validator_fallthrough=True)
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/pydantic/correctness/validator-fallthrough", 6)
    ]


def test_field_positional_default_is_advisory_and_alias_aware() -> None:
    source = (
        "from pydantic import BaseModel, Field as F\n"
        "class Item(BaseModel):\n"
        "    first: int = F(1)\n"
        "    second: int = F(default=2)\n"
        "    third: int = OtherField(3)\n"
        "class Plain:\n"
        "    value: int = F(4)\n"
        "def dependency(value: int = F(5)):\n"
        "    return value\n"
    )
    findings = pydantic_practice_findings(
        source, _policy(report_field_positional_default=True)
    )

    assert [(item.rule_id, item.line, item.severity) for item in findings] == [
        ("alphus/python/pydantic/style/field-positional-default", 3, "info")
    ]


def test_static_mutable_default_factory_is_opt_in_and_narrow() -> None:
    source = (
        "from typing import Annotated\n"
        "from pydantic import BaseModel as Model, Field as F\n"
        "class Config(Model):\n"
        "    tags: list[str] = F(default_factory=list)\n"
        "    options: Annotated[dict[str, int], F(default_factory=dict)]\n"
        "    computed: list[str] = F(default_factory=load_tags)\n"
        "    contextual: list[str] = F(default_factory=lambda data: data['tags'])\n"
        "    direct: list[str] = []\n"
        "class Plain:\n"
        "    tags: list[str] = F(default_factory=list)\n"
    )

    assert pydantic_practice_findings(source, _policy()) == []
    findings = pydantic_practice_findings(
        source, _policy(prefer_static_mutable_defaults=True)
    )

    assert [(item.rule_id, item.line, item.severity) for item in findings] == [
        (
            "alphus/python/pydantic/style/static-mutable-default-factory",
            4,
            "info",
        ),
        (
            "alphus/python/pydantic/style/static-mutable-default-factory",
            5,
            "info",
        ),
    ]
    assert all("not required for isolation" in item.message for item in findings)


@pytest.mark.parametrize(
    ("builtin", "annotation"),
    [("list", "list[str]"), ("dict", "dict[str, int]")],
)
def test_static_mutable_default_factory_skips_shadowed_builtins(
    builtin: str, annotation: str
) -> None:
    source = (
        "from pydantic import BaseModel, Field\n"
        "def custom_factory(): return None\n"
        f"{builtin} = custom_factory\n"
        "class Item(BaseModel):\n"
        f"    value: {annotation} = Field(default_factory={builtin})\n"
    )

    findings = pydantic_practice_findings(
        source, _policy(prefer_static_mutable_defaults=True), path="src/item.py"
    )

    assert findings == []


@pytest.mark.parametrize(
    ("builtin", "annotation"),
    [("list", "list[str]"), ("dict", "dict[str, int]")],
)
def test_static_mutable_default_factory_ignores_unrelated_function_locals(
    builtin: str, annotation: str
) -> None:
    source = (
        "from pydantic import BaseModel, Field\n"
        "def helper():\n"
        f"    {builtin} = custom_factory\n"
        "    return None\n"
        "class Item(BaseModel):\n"
        f"    value: {annotation} = Field(default_factory={builtin})\n"
    )

    findings = pydantic_practice_findings(
        source, _policy(prefer_static_mutable_defaults=True), path="src/item.py"
    )

    assert [item.line for item in findings] == [6]


def test_static_mutable_default_factory_respects_prior_class_binding() -> None:
    source = (
        "from pydantic import BaseModel, Field\n"
        "class Item(BaseModel):\n"
        "    list = custom_factory\n"
        "    value: list[str] = Field(default_factory=list)\n"
    )

    findings = pydantic_practice_findings(
        source, _policy(prefer_static_mutable_defaults=True), path="src/item.py"
    )

    assert findings == []


def test_pydantic_copies_static_unhashable_defaults_per_instance() -> None:
    class Defaults(BaseModel):
        tags: list[str] = []
        options: dict[str, int] = {}

    first = Defaults()
    second = Defaults()
    first.tags.append("local")
    first.options["count"] = 1

    assert second.tags == []
    assert second.options == {}
    assert first.tags is not second.tags
    assert first.options is not second.options


def test_unconstrained_any_is_limited_to_designated_public_model_paths() -> None:
    source = (
        "from typing import Any as Loose, ClassVar\n"
        "from pydantic import BaseModel\n"
        "class PublicRequest(BaseModel):\n"
        "    payload: list[Loose]\n"
        '    legacy: "Loose"\n'
        "    cache: ClassVar[Loose] = None\n"
        "    _private: Loose\n"
    )
    policy = _policy(
        report_unconstrained_any=True,
        public_model_paths=("src/api/**",),
    )
    assert pydantic_practice_findings(source, _policy(), path="src/api/models.py") == []

    findings = pydantic_practice_findings(source, policy, path="src/api/models.py")

    assert [(item.rule_id, item.line, item.severity) for item in findings] == [
        ("alphus/python/pydantic/validation/public-unconstrained-any", 4, "warning"),
        ("alphus/python/pydantic/validation/public-unconstrained-any", 5, "warning"),
    ]
    assert (
        pydantic_practice_findings(source, policy, path="src/internal/models.py") == []
    )


def test_external_schema_docs_follow_fastapi_routes_and_nested_models() -> None:
    source = (
        "from typing import Annotated, ClassVar\n"
        "from fastapi import APIRouter\n"
        "from pydantic import BaseModel, Field, PrivateAttr\n"
        "class Detail(BaseModel):\n"
        "    code: str\n"
        "    labeled: Annotated[int, Field(description='A label')]\n"
        "    count: ClassVar[int] = 0\n"
        "    _secret: str = PrivateAttr()\n"
        "class Request(BaseModel):\n"
        "    detail: Detail\n"
        "    count: int = Field(description='Number requested')\n"
        "router = APIRouter()\n"
        "@router.post('/items', response_model=Request)\n"
        "def create(item: Request) -> Request:\n"
        "    return item\n"
    )
    findings = pydantic_practice_findings(
        source, _policy(report_external_model_docs=True)
    )

    assert [
        (item.rule_id, item.line, item.severity, item.message) for item in findings
    ] == [
        (
            "alphus/python/pydantic/metadata/external-schema-documentation",
            4,
            "info",
            "add a class description for this external model's JSON Schema",
        ),
        (
            "alphus/python/pydantic/metadata/external-schema-documentation",
            5,
            "info",
            "add a JSON Schema description for external field 'code'",
        ),
        (
            "alphus/python/pydantic/metadata/external-schema-documentation",
            9,
            "info",
            "add a class description for this external model's JSON Schema",
        ),
        (
            "alphus/python/pydantic/metadata/external-schema-documentation",
            10,
            "info",
            "add a JSON Schema description for external field 'detail'",
        ),
    ]


def test_external_model_docs_can_be_configured_for_other_interfaces() -> None:
    source = (
        "from pydantic import BaseModel, ConfigDict, Field\n"
        "class PublicRequest(BaseModel):\n"
        '    """A public request."""\n'
        "    value: str = Field(description='A value')\n"
        "class ConfiguredResponse(BaseModel):\n"
        "    model_config = ConfigDict(json_schema_extra={'description': 'Response'})\n"
        "    value: str = Field(json_schema_extra={'description': 'A value'})\n"
        "class UndocumentedModel(BaseModel):\n"
        "    value: str = Field(description='A value')\n"
        "class InternalModel(BaseModel):\n"
        "    value: str\n"
    )
    assert (
        pydantic_practice_findings(source, _policy(report_external_model_docs=True))
        == []
    )
    findings = pydantic_practice_findings(
        source,
        _policy(
            report_external_model_docs=True,
            external_model_names=(
                "PublicRequest",
                "ConfiguredResponse",
                "UndocumentedModel",
            ),
        ),
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/pydantic/metadata/external-schema-documentation", 8),
    ]


def test_external_model_docs_support_imported_custom_pydantic_bases() -> None:
    source = (
        "from pydantic import Field\n"
        "from alphus.policy.base import StrictModel\n"
        "class PublicPolicy(StrictModel):\n"
        '    """A public policy model."""\n'
        "    name: str = Field(description='Policy name')\n"
        "class PrivatePolicy(StrictModel):\n"
        "    name: str\n"
    )
    findings = pydantic_practice_findings(
        source,
        _policy(
            report_external_model_docs=True,
            external_model_names=("PublicPolicy", "PrivatePolicy"),
        ),
    )

    assert [(item.line, item.message) for item in findings] == [
        (6, "add a class description for this external model's JSON Schema"),
        (7, "add a JSON Schema description for external field 'name'"),
    ]


@pytest.mark.parametrize(
    "options",
    [
        (("report_unvalidated_construct", "yes"),),
        (("report_unsupported_rule", True),),
        (("external_model_names", ("not-a-name",)),),
        (("external_model_names", ("PublicModel", "PublicModel")),),
        (("report_unconstrained_any", True),),
        (("public_model_paths", ("src/api/**", "src/api/**")),),
    ],
)
def test_pydantic_policy_rejects_malformed_or_unknown_options(
    options: tuple[tuple[str, object], ...],
) -> None:
    with pytest.raises(ValidationError):
        PydanticPracticePolicy.model_validate(
            dict((("extensions", (".py",)), *options))
        )
