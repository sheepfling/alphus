"""Source-only tests for the opt-in dynamic Markdown advisory."""

from __future__ import annotations

import json
import subprocess
from io import StringIO
from pathlib import Path

import pytest

from alphus.cli import main
from alphus.config import DynamicMarkdownPolicy, load_config_stream
from alphus.execution.profile_manifest import gate_manifest_entry
from alphus.gates.review.dynamic_markdown import (
    check_dynamic_markdown,
    dynamic_markdown_findings,
)
from alphus.gates.review.runners import REVIEW_RULE_RUNNERS
from alphus.policy.base import MissingPolicyError, QualityRuleName
from alphus.policy.catalog import RULE_SPECS
from alphus.policy.orchestration import CheckPolicies, RuleRunStep
from alphus.policy.review import DynamicMarkdownException


def test_fstring_table_row_reports_dynamic_values_with_context() -> None:
    findings = dynamic_markdown_findings(
        "def render(label, value):\n"
        '    row = f"| {label} | {value} |\\n"\n'
        "    alias = row\n"
        "    return alias\n",
        path="src/render.py",
    )

    assert len(findings) == 2
    assert all(finding.path == "src/render.py" for finding in findings)
    assert all(finding.line == 2 for finding in findings)
    assert all(finding.severity == "warning" for finding in findings)
    assert all("table cell" in finding.message for finding in findings)
    assert any("'label'" in finding.message for finding in findings)
    assert any("'value'" in finding.message for finding in findings)
    assert all(
        "does not prove invalid rendered output" in finding.message
        for finding in findings
    )
    assert "table cell" in str(findings[0].to_wire()["message"])


def test_concatenation_and_format_report_link_contexts() -> None:
    concatenated = dynamic_markdown_findings(
        'def render(label, target):\n    return "[" + label + "](" + target + ")"\n'
    )
    formatted = dynamic_markdown_findings(
        'def render(label, target):\n    return "[{}]({})".format(label, target)\n'
    )

    for findings in (concatenated, formatted):
        assert len(findings) == 2
        assert {"link label", "link destination"} == {
            context
            for finding in findings
            for context in ("link label", "link destination")
            if context in finding.message
        }
        assert all("tested shared builder" in finding.message for finding in findings)


def test_format_template_alias_and_ad_hoc_replacement_remain_advisory() -> None:
    findings = dynamic_markdown_findings(
        "def render(label, target, value):\n"
        '    template = "[{}]({})"\n'
        "    link = template.format(label, target)\n"
        '    row = f"| {value} |".replace("|", "\\\\|")\n'
        '    return link + "\\n" + row\n'
    )

    assert {"link label", "link destination", "table cell"} == {
        context
        for finding in findings
        for context in ("link label", "link destination", "table cell")
        if context in finding.message
    }
    assert any("ad-hoc string replacement" in finding.message for finding in findings)


def test_declared_helper_contract_is_qualified_and_respects_shadowing() -> None:
    source = (
        "from docs.markdown_cells import escape_cell as escape\n"
        "import docs.markdown_cells as cells\n"
        "def render(value):\n"
        '    return f"| {escape(value)} |"\n'
        "def module_alias(value):\n"
        '    return f"| {cells.escape_cell(value)} |"\n'
        "def shadow(escape, value):\n"
        '    return f"| {escape(value)} |"\n'
        "def rebound(value):\n"
        "    escape = lambda item: item\n"
        '    return f"| {escape(value)} |"\n'
        "def unrelated(value):\n"
        '    return f"| {docs.markdown_cells.escape_cell(value)} |"\n'
    )

    findings = dynamic_markdown_findings(
        source,
        declared_safe_helpers=("docs.markdown_cells.escape_cell",),
    )

    assert len(findings) == 3
    assert {finding.line for finding in findings} == {8, 11, 13}
    assert all("table cell" in finding.message for finding in findings)


def test_declared_helper_contract_does_not_accept_package_import_alone() -> None:
    findings = dynamic_markdown_findings(
        "import docs.markdown_cells\n"
        "def render(value):\n"
        '    return f"| {value} |"\n'
        "    docs.markdown_cells.escape_cell(value)\n",
        declared_safe_helpers=("docs.markdown_cells.escape_cell",),
    )

    assert len(findings) == 1


def test_declared_context_helpers_suppress_wrapped_code_and_block_values() -> None:
    source = (
        "from docs.markdown import (\n"
        "    code_span, code_fence, list_item, block_quote,\n"
        ")\n"
        "def render(value):\n"
        '    return f"`{code_span(value)}`\\n```text\\n{code_fence(value)}'
        '\\n```\\n- {list_item(value)}\\n> {block_quote(value)}\\n"\n'
    )

    findings = dynamic_markdown_findings(
        source,
        declared_safe_helpers=(
            "docs.markdown.code_span",
            "docs.markdown.code_fence",
            "docs.markdown.list_item",
            "docs.markdown.block_quote",
        ),
    )

    assert findings == []


def test_declared_helpers_require_qualified_names() -> None:
    with pytest.raises(ValueError, match="qualified dotted names"):
        DynamicMarkdownPolicy(
            producer_paths=("src/**",),
            declared_safe_helpers=("escape_cell",),
        )


def test_direct_branch_outputs_and_nested_functions_keep_separate_scopes() -> None:
    findings = dynamic_markdown_findings(
        "def render(enabled, value):\n"
        "    def nested(other):\n"
        '        return f"plain {other}"\n'
        "    if enabled:\n"
        '        return f"| {value} |"\n'
        "    return nested(value)\n"
    )

    assert len(findings) == 1
    assert findings[0].line == 5
    assert "table cell" in findings[0].message


def test_list_append_join_and_code_delimiters_are_recognized() -> None:
    findings = dynamic_markdown_findings(
        "def render(label, target, code):\n"
        "    parts = []\n"
        '    parts.append("[")\n'
        "    parts.append(label)\n"
        '    parts.append("](")\n'
        "    parts.append(target)\n"
        '    parts.append(")")\n'
        '    link = "".join(parts)\n'
        '    inline = f"`{code}`"\n'
        '    fenced = f"```\\n{code}\\n```"\n'
        "    return link + inline + fenced\n"
    )

    contexts = [finding.message for finding in findings]
    assert any("link label" in message for message in contexts)
    assert any("link destination" in message for message in contexts)
    assert any("code span" in message for message in contexts)
    assert any("code fence" in message for message in contexts)
    assert any("local append/join assembly" in message for message in contexts)


def test_loop_appends_retain_one_reviewable_row_for_later_join() -> None:
    findings = dynamic_markdown_findings(
        "def render(values):\n"
        "    parts = []\n"
        "    for value in values:\n"
        "        parts.append('| ')\n"
        "        parts.append(value)\n"
        "        parts.append(' |\\n')\n"
        "    return ''.join(parts)\n"
    )

    assert len(findings) == 1
    assert findings[0].line == 5
    assert "table cell" in findings[0].message
    assert "local append/join assembly" in findings[0].message


def test_mdutils_181_table_builder_pattern_reports_dynamic_table_cell() -> None:
    # Minimal excerpt of the nested ``table +=`` loop in mdutils 1.8.1's
    # ``mdutils/tools/Table.py::Table.create_table``. The upstream implementation
    # stringifies a cell and escapes pipes before appending its closing pipe.
    source = (
        "def create_table(text, rows, columns):\n"
        '    table = "\\n"\n'
        "    index = 0\n"
        "    if columns * rows == len(text):\n"
        "        for row in range(rows + 1):\n"
        "            if row == 1:\n"
        '                table += "| --- |\\n"\n'
        "            else:\n"
        '                table += "|"\n'
        "                for _ in range(columns):\n"
        '                    table += str(text[index]).replace("|", r"\\|") + "|"\n'
        "                    index += 1\n"
        '                table += "\\n"\n'
        "    return table\n"
    )

    findings = dynamic_markdown_findings(source, path="mdutils/tools/Table.py")

    assert len(findings) == 1
    assert findings[0].line == 11
    assert "table cell" in findings[0].message
    assert "does not prove invalid rendered output" in findings[0].message


def test_nested_list_and_blockquote_composition_report_their_contexts() -> None:
    findings = dynamic_markdown_findings(
        "def render(item, quote):\n"
        '    return f"- {item}\\n  1. {quote}\\n> {quote}\\n"\n'
    )

    contexts = {
        finding.message.partition("Markdown ")[2].partition(" by ")[0]
        for finding in findings
    }
    assert contexts == {"list item", "block quote"}
    assert any(
        "list-marker spacing, indentation, and block boundaries" in f.message
        for f in findings
    )
    assert any(
        "quote-prefix consistency and block boundaries" in f.message for f in findings
    )


def test_list_syntax_inside_fenced_code_is_not_reported_as_a_list_item() -> None:
    findings = dynamic_markdown_findings(
        'def render(value):\n    return f"```markdown\\n- {value}\\n```"\n'
    )

    assert len(findings) == 1
    assert "Markdown code fence" in findings[0].message
    assert "Markdown list item" not in findings[0].message


def test_static_prose_non_markdown_and_reassigned_aliases_are_ignored() -> None:
    source = (
        "def render(name, rate):\n"
        '    prose = f"Hello {name}"\n'
        '    punctuation = f"rate {rate} | limit"\n'
        '    row = f"| {name} |"\n'
        '    row = "plain text"\n'
        "    return prose + punctuation + row\n"
    )

    assert dynamic_markdown_findings(source) == []


def test_static_link_and_non_markdown_link_prose_are_ignored() -> None:
    source = (
        "def render(label, target):\n"
        '    static = "[documentation](https://example.test/guide)"\n'
        '    prose = f"See {label} at {target}"\n'
        "    return static + prose\n"
    )

    assert dynamic_markdown_findings(source) == []


def test_unknown_branch_join_does_not_resolve_ambiguous_alias() -> None:
    findings = dynamic_markdown_findings(
        "def render(enabled, value):\n"
        "    if enabled:\n"
        '        row = f"| {value} |"\n'
        "    else:\n"
        '        row = "plain"\n'
        "    return row\n"
    )

    assert findings == []


def test_markdown_import_does_not_suppress_separate_manual_construction() -> None:
    findings = dynamic_markdown_findings(
        "import markdown\n"
        "def render(label, target):\n"
        '    return f"[{label}]({target})"\n'
    )

    assert len(findings) == 2


def test_policy_limits_scanning_to_selected_paths_and_reasoned_exceptions(
    tmp_path: Path,
) -> None:
    included = tmp_path / "src" / "render.py"
    excluded = tmp_path / "src" / "legacy.py"
    included.parent.mkdir()
    included.write_text('def render(x):\n    return f"| {x} |"\n', encoding="utf-8")
    excluded.write_text('def render(x):\n    return f"| {x} |"\n', encoding="utf-8")
    policy = DynamicMarkdownPolicy(
        extensions=(".py",),
        exclude=(),
        producer_paths=("src/**",),
        exceptions=(
            DynamicMarkdownException(
                paths=("src/legacy.py",),
                reason="Reviewed low-level serializer keeps its output dialect stable.",
            ),
        ),
    )

    findings = check_dynamic_markdown(
        tmp_path,
        (Path("src/render.py"), Path("src/legacy.py"), Path("tests/test_render.py")),
        policy,
    )

    assert findings
    assert {finding.path for finding in findings} == {"src/render.py"}


def test_declared_producer_scope_can_include_selected_python_scripts(
    tmp_path: Path,
) -> None:
    script = tmp_path / "scripts" / "publish_release.py"
    script.parent.mkdir()
    script.write_text(
        "def render(name):\n    return f'| {name} |\\n'\n", encoding="utf-8"
    )
    policy = DynamicMarkdownPolicy(
        extensions=(".py",),
        exclude=(),
        producer_paths=("scripts/**",),
    )

    findings = check_dynamic_markdown(
        tmp_path,
        (Path("scripts/publish_release.py"), Path("src/unselected.py")),
        policy,
    )

    assert len(findings) == 1
    assert findings[0].path == "scripts/publish_release.py"
    assert findings[0].line == 2
    assert "table cell" in findings[0].message


def test_dynamic_markdown_policy_requires_explicit_producer_paths() -> None:
    try:
        DynamicMarkdownPolicy(extensions=(".py",), exclude=(), producer_paths=())
    except ValueError as error:
        assert "producer_paths" in str(error)
    else:
        raise AssertionError("empty producer scope must be rejected")


def test_dynamic_markdown_is_registered_as_a_findings_rule() -> None:
    rule: QualityRuleName = "dynamic-markdown"

    assert RULE_SPECS[rule].policy_field == "dynamic_markdown"
    assert RULE_SPECS[rule].output_shape.value == "findings"
    assert "dynamic_markdown" in CheckPolicies.model_fields
    assert rule in REVIEW_RULE_RUNNERS
    assert RuleRunStep(kind="rule", name="Markdown review", rule=rule).rule == rule


def test_rule_stays_off_without_policy_and_requires_policy_when_selected() -> None:
    config = load_config_stream(StringIO("schema_version = 1\n"))

    assert config.checks.dynamic_markdown is None
    try:
        config.checks.require_rule("dynamic-markdown")
    except MissingPolicyError as error:
        assert "dynamic_markdown" in str(error)
    else:
        raise AssertionError("selected rule without policy must be rejected")


def test_consumer_can_select_dynamic_markdown_in_a_profile() -> None:
    config = load_config_stream(
        StringIO(
            """
            schema_version = 1

            [checks.dynamic_markdown]
            extensions = [".py"]
            producer_paths = ["src/app/markdown/**"]
            exclude = ["src/app/markdown/generated/**"]

            [orchestration]
            default_profile = "markdown-review"

            [[orchestration.steps]]
            kind = "rule"
            name = "Markdown review"
            rule = "dynamic-markdown"

            [[orchestration.profiles]]
            name = "markdown-review"
            steps = ["Markdown review"]
            """
        )
    )

    assert config.checks.dynamic_markdown is not None
    assert config.checks.dynamic_markdown.producer_paths == ("src/app/markdown/**",)
    assert config.orchestration is not None
    assert config.orchestration.profiles[0].name == "markdown-review"
    entry = gate_manifest_entry(config.orchestration.steps[0], config)
    assert entry.gate_id == "alphus/rule/dynamic-markdown"


def test_consumer_cli_runs_selected_markdown_script_and_emits_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True
    )
    script = tmp_path / "scripts" / "generate_notes.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        'def render(value):\n    return f"| {value} |\\n"\n', encoding="utf-8"
    )
    excluded = tmp_path / "scripts" / "generated" / "render.py"
    excluded.parent.mkdir(parents=True)
    excluded.write_text(
        'def render(value):\n    return f"| {value} |\\n"\n', encoding="utf-8"
    )
    config = tmp_path / "quality.toml"
    config.write_text(
        """
schema_version = 1

[files]
include = ["scripts/**/*.py"]
exclude = []

[checks.dynamic_markdown]
extensions = [".py"]
producer_paths = ["scripts/**"]
exclude = ["scripts/generated/**"]

[orchestration]
default_profile = "markdown-review"

[[orchestration.steps]]
kind = "rule"
name = "Markdown source review"
rule = "dynamic-markdown"

[[orchestration.profiles]]
name = "markdown-review"
steps = ["Markdown source review"]
""",
        encoding="utf-8",
    )

    result = main(
        [
            "--root",
            str(tmp_path),
            "--config",
            str(config),
            "--run",
            "--profile",
            "markdown-review",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert len(payload["steps"]) == 1
    assert payload["steps"][0]["name"] == "Markdown source review"
    assert payload["steps"][0]["status"] == "passed"
    findings = payload["steps"][0]["findings"]
    assert len(findings) == 1
    assert (
        findings[0]["rule_id"]
        == "alphus/python/none/maintainability/dynamic-markdown-assembly"
    )
    assert findings[0]["path"] == "scripts/generate_notes.py"
    assert findings[0]["line"] == 2
    assert "table cell" in findings[0]["message"]
