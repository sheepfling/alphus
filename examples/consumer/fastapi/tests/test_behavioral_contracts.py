"""Optional local HTTP tests that need no production services or credentials."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("fastapi.testclient")
TestClient = cast(Any, importlib.import_module("fastapi.testclient")).TestClient

_ROUTES_PATH = Path(__file__).parents[1] / "src" / "routes.py"
_SPEC = importlib.util.spec_from_file_location("fastapi_example_routes", _ROUTES_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
routes = cast(ModuleType, _MODULE)


def test_authentication_and_dependency_cleanup_without_external_services() -> None:
    routes.service_events.clear()
    routes.app.dependency_overrides.clear()

    def test_user() -> str:
        return "example-token"

    def test_service() -> Iterator[object]:
        routes.service_events.append("override-open")
        try:
            yield routes.ItemService()
        finally:
            routes.service_events.append("override-close")

    with TestClient(routes.app) as client:
        rejected = client.get("/items/7")
        routes.service_events.clear()
        routes.app.dependency_overrides[routes.oauth2_scheme] = test_user
        routes.app.dependency_overrides[routes.get_item_service] = test_service
        accepted = client.get("/items/7")
    routes.app.dependency_overrides.clear()

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == {"item_id": 7}
    assert routes.service_events == ["override-open", "override-close"]
