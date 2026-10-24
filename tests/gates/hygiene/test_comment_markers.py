"""Comment-marker checks across supported source syntaxes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.cli import main
from alphus.gates.hygiene.comment_markers import check_comment_markers
from alphus.policy.sources import CommentMarkerPolicy


def _findings(
    root: Path, name: str, source: str, *, extensions: tuple[str, ...]
) -> list[tuple[int | None, str]]:
    path = root / name
    path.write_text(source, encoding="utf-8")
    policy = CommentMarkerPolicy(
        extensions=extensions,
        markers=("TODO", "FIXME", "HACK", "XXX", "XXXX"),
    )
    return [
        (finding.line, finding.message)
        for finding in check_comment_markers(root, [Path(name)], policy)
    ]


def test_python_comments_exclude_strings_and_identifiers(tmp_path: Path) -> None:
    source = (
        "label = '# TODO data'\n"
        "doc = '''FIXME is ordinary text'''\n"
        "TODO_value = 1\n"
        "# TODO: remove the shortcut\n"
        "value = 2  # fixme before release\n"
        "# TODOISH is not a marker\n"
    )
    findings = _findings(tmp_path, "sample.py", source, extensions=(".py",))
    assert findings == [
        (4, "temporary-work marker TODO in comment"),
        (5, "temporary-work marker FIXME in comment"),
    ]


def test_python_stubs_use_the_same_comment_parser(tmp_path: Path) -> None:
    findings = _findings(
        tmp_path,
        "sample.pyi",
        "def run() -> None: ...  # XXX\n",
        extensions=(".pyi",),
    )
    assert findings == [(1, "temporary-work marker XXX in comment")]


def test_javascript_and_cpp_comments_ignore_strings_and_raw_strings(
    tmp_path: Path,
) -> None:
    javascript = (
        'const url = "https://example.test/TODO";\n'
        "const template = `// HACK text`;\n"
        "// FIXME: replace shortcut\n"
        "/* ordinary line\n"
        " * XXXX remove this branch */\n"
    )
    assert _findings(tmp_path, "sample.ts", javascript, extensions=(".ts",)) == [
        (3, "temporary-work marker FIXME in comment"),
        (5, "temporary-work marker XXXX in comment"),
    ]
    cpp = (
        'auto text = R"tag(// HACK inside literal)tag";\n'
        'auto other = "/* TODO inside literal */";\n'
        "// TODO: simplify\n"
    )
    assert _findings(tmp_path, "sample.cpp", cpp, extensions=(".cpp",)) == [
        (3, "temporary-work marker TODO in comment")
    ]


def test_toml_comments_ignore_quoted_and_multiline_values(tmp_path: Path) -> None:
    source = (
        "label = '# HACK in value'\n"
        "text = '''\n"
        "# TODO in multiline value\n"
        "'''\n"
        "# fixme: choose a real version\n"
    )
    assert _findings(tmp_path, "settings.toml", source, extensions=(".toml",)) == [
        (5, "temporary-work marker FIXME in comment")
    ]


def test_file_exclusions_and_invalid_policy(tmp_path: Path) -> None:
    path = tmp_path / "generated.py"
    path.write_text("# TODO\n", encoding="utf-8")
    policy = CommentMarkerPolicy(
        extensions=(".py",), markers=("TODO",), exclude=("generated.py",)
    )
    assert check_comment_markers(tmp_path, [Path("generated.py")], policy) == []
    with pytest.raises(ValidationError, match="supported comment syntax"):
        CommentMarkerPolicy(extensions=(".json",), markers=("TODO",))
    with pytest.raises(ValidationError, match="unique ignoring case"):
        CommentMarkerPolicy(extensions=(".py",), markers=("TODO", "todo"))


def test_direct_cli_reports_file_and_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "sample.py").write_text("# HACK: temporary\n", encoding="utf-8")
    (tmp_path / "quality.toml").write_text(
        "schema_version = 1\n"
        "[files]\n"
        'include = ["*.py"]\n'
        "exclude = []\n"
        "[checks.comment_markers]\n"
        'extensions = [".py"]\n'
        'markers = ["HACK"]\n',
        encoding="utf-8",
    )
    arguments = [
        "--root",
        str(tmp_path),
        "--config",
        "quality.toml",
        "--rule",
        "comment-markers",
    ]
    assert main([*arguments, "--json"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert [(item["path"], item["line"], item["rule_id"]) for item in output] == [
        ("sample.py", 1, "alphus/any/none/hygiene/comment-marker-found")
    ]
    assert main(arguments) == 1
    human = capsys.readouterr().out
    assert "sample.py:1: temporary-work marker HACK in comment" in human
    assert "Comment markers: 1 violation(s)" in human
