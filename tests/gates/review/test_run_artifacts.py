from __future__ import annotations

from pathlib import Path

import pytest

from alphus.config import ProvenanceCallRole, RunArtifactPolicy
from alphus.gates.review.run_artifacts import check_run_artifacts, run_artifact_findings


def policy(**updates: object) -> RunArtifactPolicy:
    values: dict[str, object] = {"extensions": (".py",), "exclude": ()}
    values.update(updates)
    return RunArtifactPolicy.model_validate(values)


def test_conditional_write_then_read_same_declared_reused_path() -> None:
    configured = policy(
        conditional_output_readback=True,
        reused_output_path_names=("output_path",),
        output_writers=(ProvenanceCallRole(function="write_output"),),
        output_readers=(ProvenanceCallRole(function="read_output"),),
    )
    source = (
        "def build(rows, output_path):\n"
        "    if rows:\n"
        "        write_output(output_path, rows)\n"
        "    publish(read_output(output_path))\n"
    )
    findings = run_artifact_findings(source, "src/pipeline.py", configured)
    assert [finding.line for finding in findings] == [3]
    assert "possible, not proven" in findings[0].message


def test_conditional_output_rule_abstains_on_unconfigured_path_and_helper() -> None:
    configured = policy(
        conditional_output_readback=True,
        reused_output_path_names=("output_path",),
        output_writers=(ProvenanceCallRole(function="write_output"),),
        output_readers=(ProvenanceCallRole(function="read_output"),),
    )
    source = (
        "def build(rows, fresh_path, output_path):\n"
        "    if rows:\n"
        "        write_output(fresh_path, rows)\n"
        "        custom_writer(output_path, rows)\n"
        "    publish(custom_reader(output_path))\n"
    )
    assert run_artifact_findings(source, "src/pipeline.py", configured) == []


def test_conditional_output_rule_abstains_on_fresh_namespace_and_rebinding() -> None:
    configured = policy(
        conditional_output_readback=True,
        reused_output_path_names=("output_path",),
        fresh_output_path_names=("fresh_path",),
        output_writers=(ProvenanceCallRole(function="write_output"),),
        output_readers=(ProvenanceCallRole(function="read_output"),),
    )
    source = (
        "def build(rows, fresh_path, output_path):\n"
        "    if rows:\n"
        "        write_output(fresh_path, rows)\n"
        "    output_path = make_new_path()\n"
        "    if rows:\n"
        "        write_output(output_path, rows)\n"
        "    publish(read_output(output_path))\n"
    )
    assert run_artifact_findings(source, "src/pipeline.py", configured) == []


def test_helper_rebinding_suppresses_configured_name() -> None:
    configured = policy(
        conditional_output_readback=True,
        reused_output_path_names=("output_path",),
        output_writers=(ProvenanceCallRole(function="helpers.write_output"),),
        output_readers=(ProvenanceCallRole(function="helpers.read_output"),),
    )
    source = (
        "def build(rows, output_path):\n"
        "    helpers = FakeHelpers()\n"
        "    if rows:\n"
        "        helpers.write_output(output_path, rows)\n"
        "    publish(helpers.read_output(output_path))\n"
    )
    assert run_artifact_findings(source, "src/pipeline.py", configured) == []


def test_output_chain_is_grouped_once_per_path() -> None:
    configured = policy(
        conditional_output_readback=True,
        reused_output_path_names=("output_path",),
        output_writers=(ProvenanceCallRole(function="write_output"),),
        output_readers=(ProvenanceCallRole(function="read_output"),),
    )
    source = (
        "def build(first, second, output_path):\n"
        "    if first:\n"
        "        write_output(output_path, first)\n"
        "    if second:\n"
        "        write_output(output_path, second)\n"
        "    publish(read_output(output_path))\n"
    )
    findings = run_artifact_findings(source, "src/pipeline.py", configured)
    assert [finding.line for finding in findings] == [3]


def test_parse_then_provenance_digest_rereads_configured_path() -> None:
    configured = policy(
        parse_hash_reread=True,
        provenance_input_path_names=("input_path",),
        parsers=(ProvenanceCallRole(function="parse_input"),),
        digesters=(ProvenanceCallRole(function="digest_file"),),
        provenance_sinks=("record_provenance",),
    )
    source = (
        "def run(input_path):\n"
        "    model = parse_input(input_path)\n"
        "    record_provenance(digest_file(input_path))\n"
    )
    findings = run_artifact_findings(source, "src/pipeline.py", configured)
    assert [finding.line for finding in findings] == [3]
    assert "a change is not established" in findings[0].message


def test_parse_hash_rule_ignores_shared_snapshot_and_unbound_digest() -> None:
    configured = policy(
        parse_hash_reread=True,
        provenance_input_path_names=("input_path",),
        parsers=(ProvenanceCallRole(function="parse_input"),),
        digesters=(ProvenanceCallRole(function="digest_file"),),
        provenance_sinks=("record_provenance",),
    )
    same_bytes = (
        "def run(input_path):\n"
        "    raw = capture_bytes(input_path)\n"
        "    parse_bytes(raw)\n"
        "    record_provenance(digest_bytes(raw))\n"
    )
    unbound = (
        "def run(input_path):\n"
        "    parse_input(input_path)\n"
        "    digest_file(input_path)\n"
    )
    assert run_artifact_findings(same_bytes, "src/pipeline.py", configured) == []
    assert run_artifact_findings(unbound, "src/pipeline.py", configured) == []


def test_parse_hash_rule_ignores_explicit_immutable_snapshot_bytes() -> None:
    configured = policy(
        parse_hash_reread=True,
        provenance_input_path_names=("input_path",),
        immutable_snapshot_names=("snapshot",),
        parsers=(ProvenanceCallRole(function="parse_bytes"),),
        digesters=(ProvenanceCallRole(function="digest_bytes"),),
        provenance_sinks=("record_provenance",),
    )
    source = (
        "def run(input_path, snapshot):\n"
        "    parsed = parse_bytes(snapshot)\n"
        "    record_provenance(digest_bytes(snapshot))\n"
    )
    assert run_artifact_findings(source, "src/pipeline.py", configured) == []


def test_policy_requires_complete_roles_for_each_enabled_family() -> None:
    with pytest.raises(ValueError, match="conditional_output_readback needs"):
        policy(conditional_output_readback=True)
    with pytest.raises(ValueError, match="parse_hash_reread needs"):
        policy(parse_hash_reread=True)


def test_selected_file_exclusions_are_respected(tmp_path: Path) -> None:
    source = Path("src/harness.py")
    (tmp_path / source).parent.mkdir(parents=True)
    (tmp_path / source).write_text(
        "def run(rows, output_path):\n"
        "    if rows:\n"
        "        write_output(output_path, rows)\n"
        "    read_output(output_path)\n",
        encoding="utf-8",
    )
    configured = policy(
        conditional_output_readback=True,
        reused_output_path_names=("output_path",),
        output_writers=(ProvenanceCallRole(function="write_output"),),
        output_readers=(ProvenanceCallRole(function="read_output"),),
        exclude=("src/harness.py",),
    )
    assert check_run_artifacts(tmp_path, [source], configured) == []
