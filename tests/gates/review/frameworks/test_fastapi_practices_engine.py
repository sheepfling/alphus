"""Synthetic FastAPI and consumer error-code review fixtures."""

import pytest
from pydantic import ValidationError

from alphus.config import ErrorCodeCallSpec, FastApiPracticePolicy
from alphus.gates.review.frameworks.fastapi_practices import fastapi_practice_findings


def _policy(**options: object) -> FastApiPracticePolicy:
    return FastApiPracticePolicy(extensions=(".py",), **options)


def test_named_and_literal_statuses_in_known_fastapi_calls() -> None:
    source = (
        "from fastapi import APIRouter as Router, HTTPException as Failure, Response, status\n"
        "from fastapi.responses import JSONResponse as Reply\n"
        "router = Router()\n"
        "@router.post('/items', status_code=201)\n"
        "def create():\n"
        "    raise Failure(404)\n"
        "@router.get('/items', status_code=status.HTTP_200_OK)\n"
        "def list_items():\n"
        "    return Reply(content={}, status_code=202)\n"
        "Response(status_code=204)\n"
    )
    findings = fastapi_practice_findings(source, _policy(), path="src/api.py")

    assert [
        (item.rule_id, item.path, item.line, item.severity) for item in findings
    ] == [
        (
            "alphus/python/fastapi/correctness/literal-http-status",
            "src/api.py",
            4,
            "warning",
        ),
        (
            "alphus/python/fastapi/correctness/literal-http-status",
            "src/api.py",
            6,
            "warning",
        ),
        (
            "alphus/python/fastapi/correctness/literal-http-status",
            "src/api.py",
            9,
            "warning",
        ),
        (
            "alphus/python/fastapi/correctness/literal-http-status",
            "src/api.py",
            10,
            "warning",
        ),
    ]


def test_other_status_keywords_and_boolean_values_are_not_http_codes() -> None:
    source = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "custom(status_code=201)\n"
        "@app.get('/health', status_code=True)\n"
        "def health(): return {'ok': True}\n"
    )
    assert fastapi_practice_findings(source, _policy()) == []


def test_error_code_owners_are_consumer_configuration() -> None:
    source = (
        "from product.errors import Failure as Problem, Envelope as ErrorResponse\n"
        "from product.codes import Code\n"
        "Problem(409, 'input.invalid', 'Review')\n"
        "ErrorResponse(code='input.invalid')\n"
        "Problem(409, Code.INPUT_INVALID, 'Review')\n"
    )
    policy = _policy(
        report_literal_status=False,
        error_code_calls=(
            ErrorCodeCallSpec(call="product.errors.Failure", position=1),
            ErrorCodeCallSpec(call="product.errors.Envelope"),
        ),
    )
    findings = fastapi_practice_findings(source, policy)

    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/fastapi/correctness/literal-error-code", 3),
        ("alphus/python/fastapi/correctness/literal-error-code", 4),
    ]


def test_http_exception_detail_code_requires_explicit_opt_in() -> None:
    source = (
        "from starlette.exceptions import HTTPException as Failure\n"
        "Failure(400, detail={'code': 'invalid', 'message': 'Review'})\n"
    )
    assert [item.rule_id for item in fastapi_practice_findings(source, _policy())] == [
        "alphus/python/fastapi/correctness/literal-http-status"
    ]
    findings = fastapi_practice_findings(
        source, _policy(check_http_exception_detail_codes=True)
    )
    assert [(item.rule_id, item.line) for item in findings] == [
        ("alphus/python/fastapi/correctness/literal-error-code", 2),
        ("alphus/python/fastapi/correctness/literal-http-status", 2),
    ]


@pytest.mark.parametrize(
    "call", ["Failure", "project..Failure", "project.Failure()", ".project.Failure"]
)
def test_error_code_call_requires_dotted_import_path(call: str) -> None:
    with pytest.raises(ValidationError):
        ErrorCodeCallSpec(call=call)


def test_duplicate_error_code_owners_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        _policy(
            error_code_calls=(
                ErrorCodeCallSpec(call="product.errors.Failure"),
                ErrorCodeCallSpec(call="product.errors.Failure"),
            )
        )
