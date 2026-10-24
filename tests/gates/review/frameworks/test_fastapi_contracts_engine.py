"""Registered-route and generated OpenAPI checks for FastAPI consumers."""

from __future__ import annotations

import fnmatch
import importlib
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

import alphus.gates.review.frameworks.fastapi_contracts as contracts
from alphus.config import FastApiFindingOverride, FastApiPracticePolicy
from alphus.contracts.findings import Finding
from alphus.gates.review.frameworks.fastapi_contracts import (
    FastApiContractError,
    _contract_findings,
    _RouteSource,
    fastapi_contract_findings,
)
from alphus.gates.review.frameworks.fastapi_practices import (
    check_fastapi_practices,
    fastapi_practice_findings,
)


def _policy(**options: object) -> FastApiPracticePolicy:
    return FastApiPracticePolicy(extensions=(".py",), **options)


def _module_application(root: Path, source: str) -> tuple[str, FastApiPracticePolicy]:
    module_name = f"fastapi_contract_fixture_{uuid4().hex}"
    (root / f"{module_name}.py").write_text(source, encoding="utf-8")
    return module_name, _policy(application=f"{module_name}:app")


def test_contract_review_does_not_load_optional_frameworks_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import_module = importlib.import_module

    def fail_if_imported(name: str, package: str | None = None) -> ModuleType:
        if name.startswith(("fastapi", "starlette")):
            pytest.fail(f"optional framework import attempted: {name}")
        return original_import_module(name, package)

    monkeypatch.setattr(contracts.importlib, "import_module", fail_if_imported)
    assert (
        fastapi_practice_findings(
            "from fastapi import FastAPI\napp = FastAPI()\n", _policy()
        )
        == []
    )


def test_missing_optional_framework_is_reported_only_when_app_review_is_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "fastapi", None)
    with pytest.raises(FastApiContractError, match="requires FastAPI and Starlette"):
        fastapi_contract_findings(tmp_path, _policy(application="api:app"))


def test_zero_argument_application_factory_is_called_only_when_configured(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fastapi")
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    routes_module = f"factory_routes_{uuid4().hex}"
    (source_dir / f"{routes_module}.py").write_text(
        """from fastapi import APIRouter

router = APIRouter()

@router.get('/ready')
def ready() -> dict[str, str]:
    return {'status': 'ok'}
""",
        encoding="utf-8",
    )
    module_name, policy = _module_application(
        tmp_path,
        f"""from fastapi import FastAPI

def create_app() -> FastAPI:
    from {routes_module} import router

    app = FastAPI()
    app.include_router(router)
    return app
""",
    )
    configured = policy.model_copy(
        update={
            "application": f"{module_name}:create_app",
            "application_factory": True,
            "application_python_paths": ("src",),
        }
    )

    assert fastapi_contract_findings(tmp_path, configured) == []


def test_nested_routers_produce_stable_typed_contracts_and_locations(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fastapi")
    module_name, policy = _module_application(
        tmp_path,
        """from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

class Item(BaseModel):
    item_id: int

outer = APIRouter(prefix='/v1')
inner = APIRouter(prefix='/items')

@inner.get('/{item_id}', tags=['items'])
def read_item(item_id: int) -> Item:
    \"\"\"Read an item.\"\"\"
    return Item(item_id=item_id)

outer.include_router(inner)
app = FastAPI()
app.include_router(outer, prefix='/api')
""",
    )
    configured = policy.model_copy(
        update={
            "required_route_metadata": ("summary", "description", "tags"),
            "require_response_contract": True,
        }
    )

    first = fastapi_contract_findings(tmp_path, configured)
    second = fastapi_contract_findings(tmp_path, configured)

    assert first == second == []
    assert module_name in configured.application


def test_duplicate_registered_route_and_operation_ids_are_reported(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fastapi")
    _module_name, policy = _module_application(
        tmp_path,
        """from fastapi import FastAPI

app = FastAPI()

@app.get('/same', operation_id='shared')
def first() -> dict[str, str]:
    return {'ok': 'first'}

@app.get('/same', operation_id='shared')
def second() -> dict[str, str]:
    return {'ok': 'second'}

@app.post('/other', operation_id='shared')
def third() -> dict[str, str]:
    return {'ok': 'third'}
""",
    )

    with pytest.warns(UserWarning, match="Duplicate Operation ID"):
        findings = fastapi_contract_findings(tmp_path, policy)
    rule_ids = [finding.rule_id for finding in findings]

    assert rule_ids.count("alphus/python/fastapi/correctness/duplicate-route") == 1
    assert rule_ids.count("alphus/python/fastapi/metadata/duplicate-operation-id") >= 1
    assert all(finding.path.endswith(".py") for finding in findings)
    assert all(finding.line is not None for finding in findings)


def test_raw_response_exclusion_suppresses_schema_contract_advisory(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fastapi")
    _module_name, policy = _module_application(
        tmp_path,
        """from fastapi import FastAPI
from starlette.responses import Response

app = FastAPI()

@app.get('/download')
def download() -> Response:
    return Response(content=b'raw')
""",
    )
    required = policy.model_copy(update={"require_response_contract": True})
    excluded = required.model_copy(update={"exclude_route_paths": ("/download",)})

    assert [item.rule_id for item in fastapi_contract_findings(tmp_path, required)] == [
        "alphus/python/fastapi/validation/missing-response-contract"
    ]
    assert fastapi_contract_findings(tmp_path, excluded) == []


def test_openapi_security_is_policy_evidence_and_dependency_alone_is_not(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fastapi")
    _module_name, policy = _module_application(
        tmp_path,
        """from fastapi import Depends, FastAPI
from fastapi.security import OAuth2PasswordBearer

app = FastAPI()
oauth = OAuth2PasswordBearer(tokenUrl='token')

def local_check() -> str:
    return 'user'

@app.get('/private')
def private(token: str = Depends(oauth)) -> dict[str, str]:
    return {'token': token}

@app.get('/dependency-only')
def dependency_only(user: str = Depends(local_check)) -> dict[str, str]:
    return {'user': user}
""",
    )
    protected = policy.model_copy(
        update={"protected_route_paths": ("/private", "/dependency-only")}
    )

    findings = fastapi_contract_findings(tmp_path, protected)

    assert [(item.message, item.severity) for item in findings] == [
        (
            (
                "configured protected route does not require an OpenAPI security scheme: "
                "GET /dependency-only"
            ),
            "error",
        )
    ]


def test_inherited_openapi_security_counts_but_operation_empty_overrides_it(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fastapi")
    _module_name, policy = _module_application(
        tmp_path,
        """from fastapi import FastAPI

app = FastAPI()

@app.get('/inherited')
def inherited() -> dict[str, str]:
    return {'ok': 'yes'}

@app.get('/explicitly-public')
def explicitly_public() -> dict[str, str]:
    return {'ok': 'yes'}

schema = app.openapi()
schema['security'] = [{'BearerAuth': []}]
schema['paths']['/explicitly-public']['get']['security'] = []
""",
    )
    protected = policy.model_copy(
        update={"protected_route_paths": ("/inherited", "/explicitly-public")}
    )

    findings = fastapi_contract_findings(tmp_path, protected)

    assert [item.message for item in findings] == [
        (
            "configured protected route does not require an OpenAPI security scheme: "
            "GET /explicitly-public"
        )
    ]
    module = sys.modules[_module_name]
    assert isinstance(module, ModuleType)
    openapi_schema = module.__dict__["app"].openapi_schema
    assert isinstance(openapi_schema, dict)
    paths = openapi_schema.get("paths")
    assert isinstance(paths, dict)
    inherited_path = paths.get("/inherited")
    assert isinstance(inherited_path, dict)
    inherited = inherited_path.get("get")
    assert isinstance(inherited, dict)
    assert "security" not in inherited


@pytest.mark.parametrize(
    "security",
    [
        [{}],
        [{}, {"BearerAuth": []}],
    ],
)
def test_protected_routes_reject_anonymous_openapi_security_alternatives(
    tmp_path: Path, security: Sequence[Mapping[str, Sequence[str]]]
) -> None:
    pytest.importorskip("fastapi")
    _module_name, policy = _module_application(
        tmp_path,
        """from fastapi import FastAPI

app = FastAPI()

@app.get('/protected')
def protected() -> dict[str, str]:
    return {'ok': 'yes'}

schema = app.openapi()
schema['paths']['/protected']['get']['security'] = SECURITY
""".replace("SECURITY", repr(security)),
    )
    protected_policy = policy.model_copy(
        update={"protected_route_paths": ("/protected",)}
    )

    findings = fastapi_contract_findings(tmp_path, protected_policy)

    assert [item.message for item in findings] == [
        (
            "configured protected route does not require an OpenAPI security scheme: "
            "GET /protected"
        )
    ]


def test_mounted_fastapi_app_routes_use_the_mount_prefix(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fastapi")
    _module_name, policy = _module_application(
        tmp_path,
        """from fastapi import FastAPI
from pydantic import BaseModel

class Result(BaseModel):
    ok: bool

child = FastAPI()

@child.get('/')
def root() -> Result:
    return Result(ok=True)

@child.get('/ready')
def ready() -> Result:
    return Result(ok=True)

app = FastAPI()
app.mount('/internal', child)
""",
    )
    configured = policy.model_copy(
        update={
            "required_route_metadata": ("tags",),
            "require_response_contract": True,
        }
    )

    findings = fastapi_contract_findings(tmp_path, configured)

    assert [item.message for item in findings] == [
        "route requires OpenAPI tags metadata: GET /internal/",
        "route requires OpenAPI tags metadata: GET /internal/ready",
    ]
    assert findings[0].path.endswith(".py")


def test_excluded_mounted_fastapi_route_is_skipped(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    _module_name, policy = _module_application(
        tmp_path,
        """from fastapi import FastAPI
from starlette.responses import Response

child = FastAPI()

@child.get('/download')
def download() -> Response:
    return Response(content=b'raw')

app = FastAPI()
app.mount('/internal', child)
""",
    )
    configured = policy.model_copy(
        update={
            "exclude_route_paths": ("/internal/download",),
            "require_response_contract": True,
            "required_route_metadata": ("tags",),
        }
    )

    assert fastapi_contract_findings(tmp_path, configured) == []


def test_missing_and_duplicate_operation_ids_have_distinct_rule_ids() -> None:
    policy = _policy()
    sources = (
        _RouteSource("/first", "GET", "api.py", 3),
        _RouteSource("/second", "GET", "api.py", 8),
        _RouteSource("/third", "GET", "api.py", 13),
    )
    operations = (
        ("/first", "GET", {"operationId": "shared"}),
        ("/second", "GET", {"operationId": "shared"}),
        ("/third", "GET", {}),
    )

    findings = _contract_findings(operations, sources, policy)

    assert {item.rule_id for item in findings} == {
        "alphus/python/fastapi/metadata/duplicate-operation-id",
        "alphus/python/fastapi/metadata/missing-operation-id",
    }
    assert all(isinstance(item, Finding) for item in findings)
    assert all(item.line is not None for item in findings)


def test_baseline_uses_external_oasdiff_as_opt_in_without_repo_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = tmp_path / "openapi.json"
    baseline.write_text('{"openapi":"3.1.0","paths":{}}', encoding="utf-8")
    executable = tmp_path / "oasdiff"
    executable.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | 0o111)
    monkeypatch.setattr(contracts.shutil, "which", lambda _name: os.fspath(executable))
    captured_arguments: list[Sequence[str]] = []

    def compare(arguments: Sequence[str], **_kwargs: object) -> object:
        captured_arguments.append(arguments)
        return contracts.subprocess.CompletedProcess(
            arguments,
            1,
            stdout=(
                "2 breaking changes\n"
                "ERR [api-path-removed] in API GET /items/{item_id}\n"
                "WARN [response-schema-changed] in API GET /items/{item_id}\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(contracts.subprocess, "run", compare)
    policy = _policy(
        application="api:app",
        openapi_baseline="openapi.json",
        exclude_route_paths=("/health*", "/internal/?"),
    )

    findings = contracts._baseline_findings(
        tmp_path, {"openapi": "3.1.0", "paths": {}}, policy
    )

    assert len(findings) == 1
    assert (
        findings[0].rule_id
        == "alphus/python/fastapi/validation/openapi-breaking-change"
    )
    assert "GET /items/{item_id}" in findings[0].message
    arguments = captured_arguments[0]
    assert arguments[arguments.index("--format") + 1] == "singleline"
    assert arguments[arguments.index("--color") + 1] == "never"
    excluded_paths = arguments[arguments.index("--unmatch-path") + 1]
    compared_paths = (
        "/health",
        "/health/live",
        "/internal/x",
        "/internal/xy",
        "/items/{item_id}",
    )
    assert [bool(re.fullmatch(excluded_paths, path)) for path in compared_paths] == [
        any(
            fnmatch.fnmatchcase(path, pattern) for pattern in policy.exclude_route_paths
        )
        for path in compared_paths
    ]
    assert {path.name for path in tmp_path.iterdir()} == {"openapi.json", "oasdiff"}


def test_baseline_accepts_a_clean_oasdiff_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("fastapi")
    _module_name, policy = _module_application(
        tmp_path,
        """from fastapi import FastAPI

app = FastAPI()

@app.get('/items')
def items() -> dict[str, str]:
    return {'status': 'ok'}
""",
    )
    (tmp_path / "openapi.json").write_text(
        '{"openapi":"3.1.0","paths":{}}', encoding="utf-8"
    )
    configured = policy.model_copy(update={"openapi_baseline": "openapi.json"})
    monkeypatch.setattr(contracts.shutil, "which", lambda _name: "/tmp/oasdiff")

    def compare(
        arguments: Sequence[str], **_kwargs: object
    ) -> contracts.subprocess.CompletedProcess[str]:
        return contracts.subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(contracts.subprocess, "run", compare)

    assert fastapi_contract_findings(tmp_path, configured) == []


def test_configured_baseline_requires_oasdiff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "openapi.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(contracts.shutil, "which", lambda _name: None)

    with pytest.raises(FastApiContractError, match="oasdiff is required"):
        contracts._baseline_findings(
            tmp_path,
            {},
            _policy(application="api:app", openapi_baseline="openapi.json"),
        )


def test_openapi_route_exclusion_regex_matches_consumer_globs() -> None:
    patterns = ("/health*", "/internal/?")
    expression = re.compile(contracts._route_exclusion_regex(patterns))
    paths = (
        "/health",
        "/health/live",
        "/internal/x",
        "/internal/xy",
        "/items/{item_id}",
    )

    assert [expression.fullmatch(path) is not None for path in paths] == [
        any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
        for path in paths
    ]


def test_route_application_configuration_is_required_and_validated() -> None:
    with pytest.raises(ValueError, match="application is required"):
        _policy(require_response_contract=True)
    with pytest.raises(ValueError, match="dotted module and attribute"):
        _policy(application="api.app")
    with pytest.raises(ValueError, match=r"absolute POSIX globs using \* and \?"):
        _policy(application="api:app", exclude_route_paths=("health",))
    with pytest.raises(ValueError, match="reason.*20 characters"):
        FastApiFindingOverride(
            rule_id="alphus/python/fastapi/correctness/literal-http-status",
            severity="info",
            reason="too short",
        )


def test_rule_overrides_change_severity_and_require_reasoned_exclusions(
    tmp_path: Path,
) -> None:
    source_path = Path("src/routes.py")
    (tmp_path / source_path).parent.mkdir()
    (tmp_path / source_path).write_text(
        "from fastapi import HTTPException\nraise HTTPException(status_code=401)\n",
        encoding="utf-8",
    )
    adjusted = _policy(
        finding_overrides=(
            FastApiFindingOverride(
                rule_id="alphus/python/fastapi/correctness/literal-http-status",
                severity="info",
                exclude_paths=("src/routes.py",),
                reason="This example intentionally teaches literal HTTP statuses.",
            ),
        )
    )

    findings = check_fastapi_practices(tmp_path, [source_path], adjusted)

    assert findings == []
    adjusted_without_suppression = adjusted.model_copy(
        update={
            "finding_overrides": (
                FastApiFindingOverride(
                    rule_id="alphus/python/fastapi/correctness/literal-http-status",
                    severity="info",
                    reason="Keep the status advisory informative for this API team.",
                ),
            )
        }
    )
    findings = check_fastapi_practices(
        tmp_path, [source_path], adjusted_without_suppression
    )
    assert [(item.rule_id, item.severity) for item in findings] == [
        ("alphus/python/fastapi/correctness/literal-http-status", "info")
    ]
