"""Pydantic manual initializer review stays isolated from other practices."""

from alphus.config import PydanticPracticePolicy
from alphus.gates.review.frameworks.pydantic.practices import pydantic_practice_findings


def test_custom_model_validation_is_reported_but_plain_classes_are_ignored() -> None:
    source = (
        "from pydantic import BaseModel as Model\n"
        "class Item(Model):\n"
        "    value: int\n"
        "    def __init__(self, **data):\n"
        "        if not isinstance(data.get('value'), int):\n"
        "            raise TypeError('value must be an int')\n"
        "        super().__init__(**data)\n"
        "class Plain:\n"
        "    def __init__(self):\n"
        "        pass\n"
    )
    policy = PydanticPracticePolicy.model_validate(
        {"extensions": (".py",), "report_custom_init": True}
    )

    findings = pydantic_practice_findings(source, policy, path="src/models.py")

    assert [(item.rule_id, item.line, item.severity) for item in findings] == [
        ("alphus/python/pydantic/validation/custom-init", 4, "info")
    ]


def test_custom_model_initializer_review_remains_opt_in() -> None:
    source = (
        "from pydantic import BaseModel\n"
        "class Item(BaseModel):\n"
        "    value: int\n"
        "    def __init__(self, **data):\n"
        "        super().__init__(**data)\n"
    )

    assert (
        pydantic_practice_findings(
            source,
            PydanticPracticePolicy.model_validate({"extensions": (".py",)}),
        )
        == []
    )
