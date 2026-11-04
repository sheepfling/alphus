"""Effective Git attribute policy checks use Git's own attribute parser."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alphus.config import QualityGateConfig
from alphus.gates.vcs.git_quality import check_attributes, check_ignores
from alphus.gates.vcs.runners import VCS_RULE_RUNNERS
from alphus.policy.repository import (
    GitAttributeRequirement,
    GitRepositoryPolicy,
    TrackedGeneratedOutput,
    TrackedGeneratedProvenance,
)


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)


def test_attributes_rule_reports_untracked_file_and_effective_mismatch(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "--quiet")
    expected = GitAttributeRequirement(
        path="javascript/example.js", attribute="eol", value="lf"
    )

    missing = check_attributes(tmp_path, (expected,))
    assert [item.rule_id for item in missing] == [
        "alphus/repository/git/hygiene/attributes-file-untracked",
        "alphus/repository/git/hygiene/attribute-mismatch",
    ]

    (tmp_path / ".gitattributes").write_text(
        "/javascript/** text eol=crlf\n", encoding="utf-8"
    )
    _git(tmp_path, "add", ".gitattributes")
    mismatch = check_attributes(tmp_path, (expected,))
    assert [item.message for item in mismatch] == [
        "Git attribute eol is 'crlf'; expected 'lf'"
    ]

    (tmp_path / ".gitattributes").write_text(
        "/javascript/** text eol=lf\n", encoding="utf-8"
    )
    assert check_attributes(tmp_path, (expected,)) == []


def test_declared_generated_output_reports_tracked_ignored_file_with_contract(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "--quiet")
    _gitignore = tmp_path / ".gitignore"
    _gitignore.write_text("data/generated/**\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore")
    generated = tmp_path / "data/generated/client.json"
    generated.parent.mkdir(parents=True)
    generated.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", "-f", "data/generated/client.json")
    contract = TrackedGeneratedOutput(
        pattern="data/generated/**",
        generator="scripts/build_client.py",
        classification="API client output",
    )

    findings = check_ignores(tmp_path, generated_outputs=(contract,))
    generated_findings = [
        item
        for item in findings
        if item.rule_id == "alphus/repository/git/hygiene/tracked-generated-output"
    ]

    assert [(item.path, item.severity) for item in generated_findings] == [
        ("data/generated/client.json", "info")
    ]
    assert "scripts/build_client.py" in generated_findings[0].message
    assert "API client output" in generated_findings[0].message


def test_generated_output_contract_exempts_provenance_and_ignores_untracked_and_other_paths(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "--quiet")
    (tmp_path / ".gitignore").write_text("data/generated/**\n", encoding="utf-8")
    fixture = tmp_path / "data/generated/fixture.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("{}\n", encoding="utf-8")
    operator_file = tmp_path / "data/operator/report.json"
    operator_file.parent.mkdir(parents=True)
    operator_file.write_text("{}\n", encoding="utf-8")
    untracked = tmp_path / "data/generated/new.json"
    untracked.write_text("{}\n", encoding="utf-8")
    _git(
        tmp_path,
        "add",
        ".gitignore",
        "data/operator/report.json",
    )
    _git(tmp_path, "add", "-f", "data/generated/fixture.json")
    contract = TrackedGeneratedOutput(
        pattern="data/generated/**", generator="scripts/generate.py"
    )
    provenance = TrackedGeneratedProvenance(
        path="data/generated/fixture.json",
        reason="Versioned interoperability fixture with reviewed provenance",
    )

    findings = check_ignores(
        tmp_path,
        generated_outputs=(contract,),
        generated_provenance=(provenance,),
    )

    assert not any(
        item.rule_id == "alphus/repository/git/hygiene/tracked-generated-output"
        for item in findings
    )


def test_generated_output_policy_rejects_duplicate_contracts_and_provenance() -> None:
    with pytest.raises(ValueError, match="generated output patterns must be unique"):
        GitRepositoryPolicy.model_validate(
            {
                "generated_outputs": [
                    {"pattern": "data/generated/**", "generator": "build.py"},
                    {"pattern": "data/generated/**", "generator": "generate.py"},
                ]
            }
        )
    with pytest.raises(
        ValueError, match="generated output provenance paths must be unique"
    ):
        GitRepositoryPolicy.model_validate(
            {
                "generated_provenance": [
                    {"path": "data/generated/fixture.json", "reason": "sample"},
                    {"path": "data/generated/fixture.json", "reason": "sample"},
                ]
            }
        )


def test_git_ignores_runner_uses_declared_generated_output_contract(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "--quiet")
    output = tmp_path / "data/generated/schema.json"
    output.parent.mkdir(parents=True)
    output.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", "data/generated/schema.json")
    config = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {
                "git": {
                    "generated_outputs": [
                        {
                            "pattern": "data/generated/**",
                            "generator": "tools/schema.py",
                            "classification": "API schema",
                        }
                    ]
                }
            },
        }
    )

    findings = VCS_RULE_RUNNERS["git-ignores"](tmp_path, (), config)
    generated = [
        item
        for item in findings
        if item.rule_id == "alphus/repository/git/hygiene/tracked-generated-output"
    ]

    assert len(generated) == 1
    assert generated[0].path == "data/generated/schema.json"
    assert "tools/schema.py" in generated[0].message
