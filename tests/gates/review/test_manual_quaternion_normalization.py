from pathlib import Path

import pytest

from alphus.config import QuaternionNormalizationPolicy
from alphus.gates.review.manual_quaternion_normalization import (
    check_manual_quaternion_normalization,
    quaternion_normalization_sites,
)

_SOURCE = """\
import math

def normalize_attitude(w, x, y, z):
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    unit = (w / norm, x / norm, y / norm, z / norm)
    return Rotation.from_quat(unit)
"""


def _policy(**updates: object) -> QuaternionNormalizationPolicy:
    return QuaternionNormalizationPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/geometry/*.py",),
            "function_names": ("normalize_attitude",),
            "components": ("w", "x", "y", "z"),
            "square_root_helpers": ("math.sqrt",),
            "rotation_consumer_helpers": ("Rotation.from_quat",),
            **updates,
        }
    )


def test_matches_configured_four_component_normalization_flow() -> None:
    sites = quaternion_normalization_sites(_SOURCE, _policy())

    assert [
        (site.function, site.norm_line, site.components_line, site.consumer_line)
        for site in sites
    ] == [("normalize_attitude", 4, 5, 6)]


def test_rejects_vector_normalization_and_library_only_calls() -> None:
    vector = _SOURCE.replace(
        "def normalize_attitude(w, x, y, z):",
        "def normalize_attitude(w, x, y):",
    ).replace("y * y + z * z", "y * y")
    library_only = """\
def normalize_attitude(w, x, y, z):
    return Rotation.from_quat((w, x, y, z))
"""

    assert quaternion_normalization_sites(vector, _policy()) == []
    assert quaternion_normalization_sites(library_only, _policy()) == []


def test_requires_all_configured_squares_shared_divisor_and_consumer() -> None:
    incomplete_norm = _SOURCE.replace("z * z", "y * y")
    wrong_divisor = _SOURCE.replace("z / norm", "z / x")
    no_consumer_flow = _SOURCE.replace("return Rotation.from_quat(unit)", "return unit")
    unconfigured_consumer = _SOURCE.replace("Rotation.from_quat", "custom.from_quat")

    assert quaternion_normalization_sites(incomplete_norm, _policy()) == []
    assert quaternion_normalization_sites(wrong_divisor, _policy()) == []
    assert quaternion_normalization_sites(no_consumer_flow, _policy()) == []
    assert quaternion_normalization_sites(unconfigured_consumer, _policy()) == []


def test_rejects_additional_control_flow_or_intervening_statements() -> None:
    source = _SOURCE.replace(
        "    return Rotation.from_quat(unit)",
        "    if norm == 0:\n        raise ValueError()\n    return Rotation.from_quat(unit)",
    )

    assert quaternion_normalization_sites(source, _policy()) == []


def test_function_component_and_helper_configuration_are_required() -> None:
    assert (
        quaternion_normalization_sites(_SOURCE, _policy(function_names=("other",)))
        == []
    )
    assert (
        quaternion_normalization_sites(
            _SOURCE, _policy(rotation_consumer_helpers=("other.from_quat",))
        )
        == []
    )
    with pytest.raises(ValueError, match="quaternion components must be unique"):
        _policy(components=("w", "x", "x", "z"))


def test_scope_exclusions_and_finding_evidence(tmp_path: Path) -> None:
    target = tmp_path / "src/geometry/attitude.py"
    target.parent.mkdir(parents=True)
    target.write_text(_SOURCE, encoding="utf-8")
    paths = (Path("src/geometry/attitude.py"),)

    findings = check_manual_quaternion_normalization(tmp_path, paths, _policy())
    assert len(findings) == 1
    assert findings[0].rule_id == (
        "alphus/python/none/maintainability/manual-quaternion-normalization"
    )
    assert findings[0].line == 4
    assert "divides all four configured components" in findings[0].message
    assert "performance gain" in findings[0].message
    assert not check_manual_quaternion_normalization(
        tmp_path,
        paths,
        _policy(exclude=("src/geometry/attitude.py",)),
    )
    assert not check_manual_quaternion_normalization(
        tmp_path,
        paths,
        _policy(source_paths=("src/other/*.py",)),
    )
