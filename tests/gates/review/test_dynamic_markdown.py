"""Source-only tests for the opt-in dynamic Markdown advisory."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

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
