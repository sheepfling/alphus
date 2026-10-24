"""Cross-language numeric catalog matching contracts."""

from __future__ import annotations

from alphus.config import NumericLiteralSpec
from alphus.contracts.rule_tags import Framework, Scope
from alphus.gates.review.numeric_catalog import (
    NumericOperation,
    NumericUse,
    match_numeric_uses,
)


def test_cpp_adapter_can_reuse_exact_catalog_matching() -> None:
    specification = NumericLiteralSpec(
        name="inch to SI",
        values=(0.0254,),
        kind="conversion",
        replacement="a named unit conversion",
        name_tokens=("inch",),
    )
    uses = [
        NumericUse(0.0254, 7, NumericOperation.MULTIPLY, frozenset({"inch"})),
        NumericUse(0.0254, 8, NumericOperation.ADD, frozenset({"inch"})),
        NumericUse(0.0254, 9, NumericOperation.MULTIPLY, frozenset({"price"})),
    ]
    findings = match_numeric_uses(
        uses, (specification,), scope=Scope.CPP, framework=Framework.NONE
    )
    assert len(findings) == 1
    assert findings[0].line == 7
    assert findings[0].rule_id == "alphus/cpp/none/style/inline-conversion"
