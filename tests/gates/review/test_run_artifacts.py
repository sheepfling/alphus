from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from alphus.config import ProvenanceCallRole, RunArtifactPolicy
from alphus.gates.review.run_artifacts import check_run_artifacts, run_artifact_findings


def policy(**updates: object) -> RunArtifactPolicy:
    return RunArtifactPolicy.model_validate(
        {"extensions": (".py",), "exclude": (), **updates}
    )


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


def test_helper_binding_in_unrelated_function_does_not_suppress_finding() -> None:
    configured = policy(
        conditional_output_readback=True,
        reused_output_path_names=("output_path",),
        output_writers=(ProvenanceCallRole(function="write_output"),),
        output_readers=(ProvenanceCallRole(function="read_output"),),
    )
    source = (
        "def unrelated():\n"
        "    write_output = local_value\n"
        "def run(rows, output_path):\n"
        "    def nested():\n"
        "        output_path = local_path\n"
        "    if rows:\n"
        "        write_output(output_path, rows)\n"
        "    read_output(output_path)\n"
    )

    findings = run_artifact_findings(source, "src/pipeline.py", configured)

    assert [finding.line for finding in findings] == [7]


def test_local_helper_function_definition_suppresses_finding() -> None:
    configured = policy(
        conditional_output_readback=True,
        reused_output_path_names=("output_path",),
        output_writers=(ProvenanceCallRole(function="write_output"),),
        output_readers=(ProvenanceCallRole(function="read_output"),),
    )
    source = (
        "def run(rows, output_path):\n"
        "    def write_output(path, value):\n"
        "        return None\n"
        "    if rows:\n"
        "        write_output(output_path, rows)\n"
        "    read_output(output_path)\n"
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


def test_parse_then_provenance_digest_rereads_configured_path(
    tmp_path: Path,
) -> None:
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
    mutable_input = tmp_path / "synthetic-input.bin"
    mutable_input.write_bytes(b"first synthetic input")
    parsed_bytes = mutable_input.read_bytes()
    mutable_input.write_bytes(b"second synthetic input")
    digest_bytes = hashlib.sha256(mutable_input.read_bytes()).digest()
    assert parsed_bytes != mutable_input.read_bytes()
    assert digest_bytes == hashlib.sha256(b"second synthetic input").digest()

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


def test_failure_diagnostic_cleanup_before_failure_sink_is_reported() -> None:
    configured = policy(
        failure_evidence_order=True,
        failure_child_runners=("run_child",),
        failure_diagnostic_path_names=("diagnostic_path",),
        failure_cleanups=(ProvenanceCallRole(function="remove_diagnostic"),),
        failure_sinks=(
            ProvenanceCallRole(function="persist_failure", path_argument_index=1),
        ),
    )
    source = (
        "def run(diagnostic_path):\n"
        "    child = run_child()\n"
        "    if child.returncode != 0:\n"
        "        remove_diagnostic(diagnostic_path)\n"
        "        persist_failure(child.returncode, diagnostic_path)\n"
    )
    findings = run_artifact_findings(source, "src/harness.py", configured)
    assert len(findings) == 1
    assert findings[0].line == 4
    assert "loss is possible, not proven" in findings[0].message


def test_failure_evidence_order_abstains_without_exact_failure_chain() -> None:
    configured = policy(
        failure_evidence_order=True,
        failure_child_runners=("run_child",),
        failure_diagnostic_path_names=("diagnostic_path",),
        failure_cleanups=(ProvenanceCallRole(function="remove_diagnostic"),),
        failure_sinks=(
            ProvenanceCallRole(function="persist_failure", path_argument_index=1),
        ),
    )
    controls = (
        (
            "def run(diagnostic_path):\n"
            "    child = run_child()\n"
            "    if child.returncode == 0:\n"
            "        remove_diagnostic(diagnostic_path)\n"
            "        persist_failure(child.returncode, diagnostic_path)\n"
        ),
        (
            "def run(diagnostic_path):\n"
            "    child = run_child()\n"
            "    if child.returncode != 0:\n"
            "        persist_failure(child.returncode, diagnostic_path)\n"
            "        remove_diagnostic(diagnostic_path)\n"
        ),
        (
            "def run(diagnostic_path):\n"
            "    child = run_child()\n"
            "    if child.returncode != 0:\n"
            "        unknown_cleanup(diagnostic_path)\n"
            "        persist_failure(child.returncode, diagnostic_path)\n"
        ),
        (
            "def run(diagnostic_path):\n"
            "    child = run_child()\n"
            "    if child.returncode != 0:\n"
            "        remove_diagnostic(diagnostic_path)\n"
        ),
    )
    for source in controls:
        assert run_artifact_findings(source, "src/harness.py", configured) == []


def test_failure_evidence_order_abstains_when_path_or_helper_is_rebound() -> None:
    configured = policy(
        failure_evidence_order=True,
        failure_child_runners=("run_child",),
        failure_diagnostic_path_names=("diagnostic_path",),
        failure_cleanups=(ProvenanceCallRole(function="remove_diagnostic"),),
        failure_sinks=(
            ProvenanceCallRole(function="persist_failure", path_argument_index=1),
        ),
    )
    controls = (
        (
            "def run(diagnostic_path):\n"
            "    child = run_child()\n"
            "    if child.returncode != 0:\n"
            "        remove_diagnostic(diagnostic_path)\n"
            "        persist_failure(child.returncode, diagnostic_path)\n"
        ),
        (
            "def run(diagnostic_path, remove_diagnostic):\n"
            "    child = run_child()\n"
            "    if child.returncode != 0:\n"
            "        remove_diagnostic(diagnostic_path)\n"
            "        persist_failure(child.returncode, diagnostic_path)\n"
        ),
        (
            "def run(diagnostic_path):\n"
            "    def unrelated():\n"
            "        diagnostic_path = temporary_path()\n"
            "    child = run_child()\n"
            "    if child.returncode != 0:\n"
            "        remove_diagnostic(diagnostic_path)\n"
            "        persist_failure(child.returncode, diagnostic_path)\n"
        ),
        (
            "def run(diagnostic_path, persist_failure):\n"
            "    child = run_child()\n"
            "    if child.returncode != 0:\n"
            "        remove_diagnostic(diagnostic_path)\n"
            "        persist_failure(child.returncode, diagnostic_path)\n"
        ),
        (
            "def run(diagnostic_path):\n"
            "    child = run_child()\n"
            "    if child.returncode != 0:\n"
            "        diagnostic_path = make_temporary_path()\n"
            "        remove_diagnostic(diagnostic_path)\n"
            "        persist_failure(child.returncode, diagnostic_path)\n"
        ),
    )
    assert len(run_artifact_findings(controls[0], "src/harness.py", configured)) == 1
    assert len(run_artifact_findings(controls[2], "src/harness.py", configured)) == 1
    for source in (controls[1], controls[3], controls[4]):
        assert run_artifact_findings(source, "src/harness.py", configured) == []


def test_failure_evidence_order_abstains_when_child_runner_is_shadowed() -> None:
    configured = policy(
        failure_evidence_order=True,
        failure_child_runners=("run_child",),
        failure_diagnostic_path_names=("diagnostic_path",),
        failure_cleanups=(ProvenanceCallRole(function="remove_diagnostic"),),
        failure_sinks=(
            ProvenanceCallRole(function="persist_failure", path_argument_index=1),
        ),
    )
    source = (
        "def run(run_child, diagnostic_path):\n"
        "    child = run_child()\n"
        "    if child.returncode != 0:\n"
        "        remove_diagnostic(diagnostic_path)\n"
        "        persist_failure(child.returncode, diagnostic_path)\n"
    )

    assert run_artifact_findings(source, "src/harness.py", configured) == []


def test_failure_evidence_order_ignores_comprehension_target_shadow() -> None:
    configured = policy(
        failure_evidence_order=True,
        failure_child_runners=("run_child",),
        failure_diagnostic_path_names=("diagnostic_path",),
        failure_cleanups=(ProvenanceCallRole(function="remove_diagnostic"),),
        failure_sinks=(
            ProvenanceCallRole(function="persist_failure", path_argument_index=1),
        ),
    )
    source = (
        "def run(tasks, diagnostic_path):\n"
        "    [run_child for run_child in tasks]\n"
        "    child = run_child()\n"
        "    if child.returncode != 0:\n"
        "        remove_diagnostic(diagnostic_path)\n"
        "        persist_failure(child.returncode, diagnostic_path)\n"
    )

    findings = run_artifact_findings(source, "src/harness.py", configured)
    assert len(findings) == 1
    assert findings[0].line == 5


def test_runtime_metadata_without_bound_module_origin_is_reported() -> None:
    configured = policy(
        runtime_attestation_gap=True,
        runtime_module_names=("engine",),
        runtime_import_helpers=("load_runtime_module",),
        runtime_metadata_helpers=("distribution_version",),
        runtime_origin_helpers=("module_origin",),
        runtime_attestation_sinks=("record_runtime",),
    )
    mismatch = (
        "def run():\n"
        "    engine = load_runtime_module('example-engine')\n"
        "    record_runtime(distribution_version('example-engine'))\n"
    )
    findings = run_artifact_findings(mismatch, "src/harness.py", configured)
    assert len(findings) == 1
    assert findings[0].line == 3
    assert "actual origin is not determined" in findings[0].message


def test_runtime_origin_binding_and_unknown_import_styles_abstain() -> None:
    configured = policy(
        runtime_attestation_gap=True,
        runtime_module_names=("engine",),
        runtime_import_helpers=("load_runtime_module",),
        runtime_metadata_helpers=("distribution_version",),
        runtime_origin_helpers=("module_origin",),
        runtime_attestation_sinks=("record_runtime",),
    )
    bound = (
        "def run():\n"
        "    engine = load_runtime_module('example-engine')\n"
        "    record_runtime(distribution_version('example-engine'), module_origin(engine))\n"
    )
    unsupported = (
        "def run():\n"
        "    engine = import_namespace_package('example-engine')\n"
        "    record_runtime(distribution_version('example-engine'))\n"
    )
    comprehension_target = (
        "def run(tasks):\n"
        "    [module_origin for module_origin in tasks]\n"
        "    engine = load_runtime_module('example-engine')\n"
        "    record_runtime(\n"
        "        distribution_version('example-engine'), module_origin(engine)\n"
        "    )\n"
    )
    assert run_artifact_findings(bound, "src/harness.py", configured) == []
    assert run_artifact_findings(unsupported, "src/harness.py", configured) == []
    assert (
        run_artifact_findings(comprehension_target, "src/harness.py", configured) == []
    )


def test_runtime_attestation_abstains_on_shadowed_import_helper() -> None:
    configured = policy(
        runtime_attestation_gap=True,
        runtime_module_names=("engine",),
        runtime_import_helpers=("load_runtime_module",),
        runtime_metadata_helpers=("distribution_version",),
        runtime_origin_helpers=("module_origin",),
        runtime_attestation_sinks=("record_runtime",),
    )
    source = (
        "def run(load_runtime_module):\n"
        "    engine = load_runtime_module('example-engine')\n"
        "    record_runtime(distribution_version('example-engine'))\n"
    )

    assert run_artifact_findings(source, "src/harness.py", configured) == []


def test_runtime_attestation_does_not_trust_shadowed_origin_helper() -> None:
    configured = policy(
        runtime_attestation_gap=True,
        runtime_module_names=("engine",),
        runtime_import_helpers=("load_runtime_module",),
        runtime_metadata_helpers=("distribution_version",),
        runtime_origin_helpers=("module_origin",),
        runtime_attestation_sinks=("record_runtime",),
    )
    source = (
        "def run(module_origin):\n"
        "    engine = load_runtime_module('example-engine')\n"
        "    record_runtime(\n"
        "        distribution_version('example-engine'), module_origin(engine)\n"
        "    )\n"
    )

    findings = run_artifact_findings(source, "src/harness.py", configured)
    assert len(findings) == 1
    assert findings[0].line == 3


def test_policy_requires_complete_roles_for_each_enabled_family() -> None:
    with pytest.raises(ValueError, match="conditional_output_readback needs"):
        policy(conditional_output_readback=True)
    with pytest.raises(ValueError, match="parse_hash_reread needs"):
        policy(parse_hash_reread=True)
    with pytest.raises(ValueError, match="failure_evidence_order needs"):
        policy(failure_evidence_order=True)
    with pytest.raises(ValueError, match="runtime_attestation_gap needs"):
        policy(runtime_attestation_gap=True)


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
