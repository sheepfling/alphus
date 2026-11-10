"""Validate complaint provider output at the typed runtime boundary."""

from __future__ import annotations

import pytest

from alphus.contracts.findings import Finding
from alphus.plugins.complaint_registry import _validate_contribution_findings


def test_complaint_output_adapter_preserves_typed_findings() -> None:
    finding = Finding(
        rule_id="alphus/python/none/testing/example-complaint",
        path="tests/test_example.py",
        message="example",
        line=1,
    )

    assert _validate_contribution_findings([finding]) == [finding]


@pytest.mark.parametrize("value", (None, "not-a-finding", [{}]))
def test_complaint_output_adapter_rejects_untyped_results(value: object) -> None:
    with pytest.raises(TypeError, match="list of Finding values"):
        _validate_contribution_findings(value)
