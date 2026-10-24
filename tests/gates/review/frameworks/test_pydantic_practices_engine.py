"""Synthetic Pydantic source contracts for optional review findings."""

import pytest
from pydantic import ValidationError

from alphus.config import PydanticPracticePolicy
from alphus.gates.review.frameworks.pydantic_practices import pydantic_practice_findings


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


@pytest.mark.parametrize(
    "options",
    [
        (("report_unvalidated_construct", "yes"),),
        (("report_unsupported_rule", True),),
        (("external_model_names", ("not-a-name",)),),
        (("external_model_names", ("PublicModel", "PublicModel")),),
    ],
)
def test_pydantic_policy_rejects_malformed_or_unknown_options(
    options: tuple[tuple[str, object], ...],
) -> None:
    with pytest.raises(ValidationError):
        PydanticPracticePolicy.model_validate(
            dict((("extensions", (".py",)), *options))
        )
