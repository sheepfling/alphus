from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import QuaternionProductPolicy
from alphus.gates.review.manual_quaternion_product import (
    check_manual_quaternion_products,
    quaternion_product_lines,
)

_LEFT = ("lw", "lx", "ly", "lz")
_RIGHT = ("rw", "rx", "ry", "rz")
_RESULT = ("ow", "ox", "oy", "oz")


def _policy(
    *,
    function_names: tuple[str, ...] = ("multiply_quaternions",),
    result_components: tuple[str, str, str, str] = _RESULT,
    exclude: tuple[str, ...] = (),
) -> QuaternionProductPolicy:
    return QuaternionProductPolicy(
        extensions=(".py",),
        source_paths=("src/geometry/*.py",),
        function_names=function_names,
        left_components=_LEFT,
        right_components=_RIGHT,
        result_components=result_components,
        exclude=exclude,
    )


def _source(wrong_scalar: bool = False) -> str:
    scalar_x_sign = "+" if wrong_scalar else "-"
    return """\
def multiply_quaternions(lw, lx, ly, lz, rw, rx, ry, rz):
    ow, ox, oy, oz = (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )
    return ow, ox, oy, oz
""".replace("lw * rw - lx * rx", f"lw * rw {scalar_x_sign} lx * rx")


def test_detects_complete_configured_scalar_first_hamilton_product() -> None:
    assert quaternion_product_lines(_source(), _policy()) == [
        ("multiply_quaternions", 2)
    ]


def test_rejects_wrong_sign_generic_vector_and_unconfigured_function() -> None:
    assert not quaternion_product_lines(_source(wrong_scalar=True), _policy())
    generic = """\
def normalize(v):
    ow, ox, oy, oz = lw * rw, lx * rx, ly * ry, lz * rz
"""
    assert not quaternion_product_lines(generic, _policy(function_names=("normalize",)))
    assert not quaternion_product_lines(_source(), _policy(function_names=("other",)))


def test_requires_distinct_component_names() -> None:
    with pytest.raises(ValidationError, match="must be distinct"):
        _policy(result_components=("ow", "ox", "oy", "lw"))


def test_reports_only_configured_source_and_respects_exclusions(tmp_path: Path) -> None:
    path = tmp_path / "src/geometry/rotation.py"
    path.parent.mkdir(parents=True)
    path.write_text(_source(), encoding="utf-8")
    findings = check_manual_quaternion_products(
        tmp_path, (Path("src/geometry/rotation.py"),), _policy()
    )
    assert len(findings) == 1
    assert findings[0].rule_id == (
        "alphus/python/none/maintainability/manual-quaternion-kernel"
    )
    excluded = _policy(exclude=("src/geometry/**",))
    assert not check_manual_quaternion_products(
        tmp_path, (Path("src/geometry/rotation.py"),), excluded
    )
