"""Compatibility normalization for shared-utility diagnostics."""

from __future__ import annotations

import json

from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.execution.results import diagnostics_from_json, diagnostics_from_output
from alphus.gates.hygiene.shared_utilities import SharedUtilitiesReport

BYTE_HASHES = (
    "src/first.py:3:digest",
    "src/second.py:7:checksum",
)
BYTE_HASH_RULE = rule_tag(
    Scope.PYTHON,
    Framework.NONE,
    Category.MAINTAINABILITY,
    "duplicate-byte-hash-implementation",
)


def test_profile_output_retains_byte_hash_findings_with_other_shared_findings() -> None:
    report = SharedUtilitiesReport(
        duplicate_groups=(),
        file_hash_implementations=("src/one.py:2:hash_file", "src/two.py:4:digest"),
        direct_git_calls=(),
        byte_hash_implementations=BYTE_HASHES,
    )

    diagnostics = diagnostics_from_output("shared-utilities", report)

    assert [item.rule_id for item in diagnostics] == [
        rule_tag(
            Scope.PYTHON,
            Framework.NONE,
            Category.MAINTAINABILITY,
            "duplicate-file-hash-implementation",
        ),
        BYTE_HASH_RULE,
    ]
    assert all(location in diagnostics[1].message for location in BYTE_HASHES)


def test_json_adapter_accepts_byte_hash_field_and_legacy_reports() -> None:
    report = {
        "duplicate_groups": [],
        "failed": True,
        "file_hash_implementations": [],
        "direct_git_calls": [],
        "byte_hash_implementations": list(BYTE_HASHES),
    }

    diagnostics = diagnostics_from_json("shared-utilities", json.dumps(report))

    assert [item.rule_id for item in diagnostics] == [BYTE_HASH_RULE]
    assert all(location in diagnostics[0].message for location in BYTE_HASHES)

    legacy = {**report, "failed": False}
    legacy.pop("byte_hash_implementations")
    assert diagnostics_from_json("shared-utilities", json.dumps(legacy)) == []
