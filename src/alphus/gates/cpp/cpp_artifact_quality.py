"""Command line interface for C++ artifact inventory and policy checks."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from alphus.gates.cpp.artifact_contracts import (
    ArtifactScanOptions,
    parse_artifact_baseline,
)
from alphus.gates.cpp.artifact_policy import evaluate, load_policy, manifest_digest
from alphus.gates.cpp.artifact_scan import DEFAULT_INCLUDE_GLOBS, scan_directory
from alphus.support.data_access import validate_json_value
from alphus.support.reporting import OutputFormat, ReportLine, ReportView, emit_report
from alphus.support.source_text import read_utf8_text


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("scan", "check"):
        child = commands.add_parser(command)
        child.add_argument("root", type=Path)
        child.add_argument("--include", action="append")
        child.add_argument("--exclude", action="append")
        child.add_argument("--objdump", default="objdump")
        child.add_argument("--no-sections", action="store_true")
        child.add_argument("--debug-dominance-min-bytes", type=int)
        child.add_argument("--max-review-examples", type=int)
        child.add_argument("--section-timeout-seconds", type=float)
        child.add_argument("--run-id")
        child.add_argument("--manifest", type=Path)
        child.add_argument("--output", type=Path)
        child.add_argument(
            "--format",
            type=OutputFormat,
            choices=list(OutputFormat),
            default=OutputFormat.AUTO,
        )
        if command == "check":
            child.add_argument("--policy", required=True, type=Path)
            child.add_argument("--baseline", type=Path)
    arguments = parser.parse_args(argv)
    try:
        policy = load_policy(arguments.policy) if arguments.command == "check" else None
        includes: Sequence[str] = arguments.include or (
            policy["include"]
            if policy is not None and policy["include"]
            else DEFAULT_INCLUDE_GLOBS
        )
        excludes: Sequence[str] = arguments.exclude or (
            policy["exclude"] if policy is not None else []
        )
        defaults = (
            policy.get("scan", ArtifactScanOptions())
            if policy
            else ArtifactScanOptions()
        )
        options = ArtifactScanOptions(
            debug_dominance_min_bytes=(
                arguments.debug_dominance_min_bytes
                if arguments.debug_dominance_min_bytes is not None
                else defaults.debug_dominance_min_bytes
            ),
            max_review_examples=(
                arguments.max_review_examples
                if arguments.max_review_examples is not None
                else defaults.max_review_examples
            ),
            section_timeout_seconds=(
                arguments.section_timeout_seconds
                if arguments.section_timeout_seconds is not None
                else defaults.section_timeout_seconds
            ),
        )
        inventory = scan_directory(
            arguments.root,
            includes=includes,
            excludes=excludes,
            section_tool=arguments.objdump,
            options=options,
            measure_sections=not arguments.no_sections,
            include_unix_executables=not arguments.include
            and not (policy and policy.get("include")),
        )
        report = inventory.to_wire()
        report["run_id"] = arguments.run_id
        if arguments.manifest:
            report["manifest_sha256"] = manifest_digest(
                arguments.manifest, arguments.run_id
            )
        if policy is not None:
            baseline = (
                parse_artifact_baseline(
                    validate_json_value(read_utf8_text(arguments.baseline))
                )
                if arguments.baseline
                else None
            )
            report["gate"] = evaluate(report, policy, baseline)
        totals = report["totals"]
        gate = report.get("gate")
        gate_findings = gate["findings"] if gate is not None else []
        passed = gate["passed"] if gate is not None else True
        view = ReportView(
            "artifacts",
            passed,
            (
                f"artifacts={totals['count']} executables={totals['executable_count']} "
                f"bytes={totals['bytes']} findings={len(gate_findings)}"
            ),
            tuple(
                ReportLine(
                    code=finding["code"],
                    message=f"observed={finding['observed']} limit={finding['limit']}",
                    path=finding.get("path", ""),
                )
                for finding in gate_findings
            ),
        )
        emit_report(report, view, arguments.output, arguments.format)
        return 0 if report.get("gate", {}).get("passed", True) else 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"artifact quality: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
