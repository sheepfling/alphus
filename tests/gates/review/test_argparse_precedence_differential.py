"""Bridge AST findings to real files for bounded, trusted synthetic declarations.

Only source assembled from literals in this test is executed. The advisory
itself reads that same source without importing or executing consumer modules.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from alphus.config import ArgparsePrecedencePolicy
from alphus.gates.review.argparse_precedence import check_argparse_precedence


@pytest.mark.parametrize(
    ("constructor", "declarations", "expected", "risk", "returncode"),
    [
        ("", 'child.add_argument("--output", dest="output_path")', None, True, 0),
        (
            "",
            'child.add_argument("--output", dest="output_path", default="child.txt")',
            "child.txt",
            True,
            0,
        ),
        (
            "",
            'child.add_argument("--output", dest="output_path", default=argparse.SUPPRESS)',
            "requested.txt",
            False,
            0,
        ),
        (
            ', argument_default="constructor.txt"',
            'child.add_argument("--output", dest="output_path")',
            "constructor.txt",
            True,
            0,
        ),
        (
            ", argument_default=argparse.SUPPRESS",
            'child.add_argument("--output", dest="output_path")',
            "requested.txt",
            False,
            0,
        ),
        (
            "",
            (
                'child.set_defaults(output_path="configured.txt")\n'
                'child.add_argument("--output", dest="output_path")'
            ),
            "configured.txt",
            True,
            0,
        ),
        (
            "",
            (
                'child.set_defaults(output_path="configured.txt")\n'
                'child.add_argument("--output", dest="output_path", default="action.txt")'
            ),
            "action.txt",
            True,
            0,
        ),
        (
            "",
            (
                'child.set_defaults(output_path="configured.txt")\n'
                'child.add_argument("--output", dest="output_path", default=argparse.SUPPRESS)'
            ),
            "configured.txt",
            True,
            0,
        ),
        (
            "",
            (
                'child.add_argument("--output", dest="output_path", default=argparse.SUPPRESS)\n'
                'child.set_defaults(output_path="configured.txt")'
            ),
            "configured.txt",
            True,
            0,
        ),
        (
            "",
            (
                'child.add_argument("--output", dest="output_path", default="action.txt")\n'
                "child.set_defaults(output_path=argparse.SUPPRESS)"
            ),
            "==SUPPRESS==",
            True,
            0,
        ),
        (
            "",
            'child.add_argument("--report", dest="output_path", default="report.txt")',
            "report.txt",
            True,
            0,
        ),
        (
            "",
            'child.add_argument("--output", dest="output_path", required=True)',
            None,
            False,
            2,
        ),
        (
            "",
            'child.set_defaults(output_path="configured.txt")',
            "configured.txt",
            True,
            0,
        ),
    ],
    ids=[
        "implicit-none",
        "explicit-default",
        "action-suppress",
        "constructor-default",
        "constructor-suppress",
        "set-before-inherited",
        "set-before-action-override",
        "set-before-suppress-still-fills",
        "set-after-suppress",
        "parser-suppress-sentinel-trap",
        "different-flags-custom-dest",
        "required-child-rejects-root-only",
        "parser-default-without-child-action",
    ],
)
def test_static_risk_matches_executable_omitted_child_output(
    tmp_path: Path,
    constructor: str,
    declarations: str,
    expected: str | None,
    risk: bool,
    returncode: int,
) -> None:
    source = (
        "import argparse\n"
        "from pathlib import Path\n"
        "root = argparse.ArgumentParser()\n"
        'root.add_argument("--output", dest="output_path", default="root-default.txt")\n'
        "commands = root.add_subparsers(required=True)\n"
        f'child = commands.add_parser("render"{constructor})\n'
        f"{declarations}\n"
        "args = root.parse_args()\n"
        "if args.output_path is not None:\n"
        '    Path(args.output_path).write_text("rendered\\n", encoding="utf-8")\n'
    )
    script = tmp_path / "synthetic.py"
    script.write_text(source, encoding="utf-8")
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    result = subprocess.run(
        [sys.executable, str(script), "--output", "requested.txt", "render"],
        cwd=output_directory,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == returncode, result.stderr
    expected_files = {} if expected is None else {expected: "rendered\n"}
    assert {
        path.name: path.read_text(encoding="utf-8")
        for path in output_directory.iterdir()
    } == expected_files

    policy = ArgparsePrecedencePolicy(extensions=(".py",), source_paths=("*.py",))
    findings = check_argparse_precedence(tmp_path, [Path("synthetic.py")], policy)
    assert not any(
        item.rule_id.endswith("argparse-precedence-unassessed") for item in findings
    )
    risks = [
        item for item in findings if item.rule_id.endswith("argparse-default-overwrite")
    ]
    assert len(risks) == int(risk), findings
    if risks:
        assert "output_path" in risks[0].message
        assert repr(expected) in risks[0].message
        assert "remove parser-level" in risks[0].message
        assert "set_defaults(...=SUPPRESS) is not a reset" in risks[0].message
