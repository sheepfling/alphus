"""Synthetic Pydantic source contracts for optional review findings."""

from alphus.config import PydanticPracticePolicy
from alphus.gates.review.pydantic_practices import pydantic_practice_findings


def _policy(**options: bool) -> PydanticPracticePolicy:
    return PydanticPracticePolicy(extensions=(".py",), **options)


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
