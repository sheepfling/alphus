"""Keep advisory test checks focused on concrete brittle dependencies."""

from pathlib import Path

import pytest

from alphus.config import TestQualityPolicy as Policy
from alphus.gates.review.test_quality import check_test_quality, python_findings

POLICY = Policy(
    extensions=[".py"],
    exclude=[],
    ephemeral_document_patterns=["docs/plans/**", "PLAN.md"],
)
NARRATIVE = (
    "During the migration the coordinator prepares a detailed narrative describing "
    "the work that should happen next, including the order in which people should "
    "review their changes and the assumptions they should check before proceeding. "
    "The report also explains why the schedule may change as new information arrives, "
    "how the team should communicate progress, and which follow-up questions should "
    "be discussed at the next planning session rather than being treated as a stable "
    "part of the application interface."
)


def scan(source: str, policy: Policy = POLICY) -> list[tuple[str, int | None]]:
    return [
        (item.rule_id, item.line)
        for item in python_findings(source, "tests/test_report.py", policy)
    ]


def test_large_exact_narrative_and_local_aliases_warn_at_the_assertion() -> None:
    source = (
        f"def test_report():\n expected = {NARRATIVE!r}\n"
        " alias = expected\n assert render() == alias\n"
    )
    findings = python_findings(source, "tests/test_report.py", POLICY)

    assert [(item.rule_id, item.line, item.severity) for item in findings] == [
        ("alphus/python/none/testing/large-prose-assertion", 4, "warning")
    ]
    assert findings[0].path == "tests/test_report.py"


@pytest.mark.parametrize(
    "assertion",
    [
        f"assert render() == {NARRATIVE!r}",
        f"assert {NARRATIVE!r} == render()",
    ],
)
def test_direct_narrative_operands_are_symmetric(assertion: str) -> None:
    assert scan(f"def test_report():\n {assertion}\n") == [
        ("alphus/python/none/testing/large-prose-assertion", 2)
    ]


@pytest.mark.parametrize(
    "expression",
    [
        f"{NARRATIVE!r} in render()",
        f"render() != {NARRATIVE!r}",
        f"scanner({NARRATIVE!r}) == []",
        "render() == 'File checked: one finding.'",
        "render() == ('token' * 400)",
        "render() == generated_expected()",
    ],
)
def test_non_exact_compact_nested_or_dynamic_assertions_are_out_of_scope(
    expression: str,
) -> None:
    assert scan(f"def test_report():\n assert {expression}\n") == []


def test_parseable_source_and_structured_json_contracts_are_not_prose() -> None:
    source_fixture = "\n".join(
        f"field_{index} = 'a complete value for the source fixture'"
        for index in range(15)
    )
    json_fixture = (
        '{"description": ' + repr(NARRATIVE).replace("'", '"') + ', "valid": true}'
    )
    assert (
        scan(f"def test_source():\n assert transform() == {source_fixture!r}\n") == []
    )
    assert scan(f"def test_schema():\n assert serialize() == {json_fixture!r}\n") == []


def test_both_thresholds_apply_and_the_boundary_is_inclusive() -> None:
    value = "a b c d e f g h i j k l"
    source = f"def test_report():\n assert render() == {value!r}\n"
    assert scan(
        source,
        POLICY.model_copy(
            update={"large_prose_min_chars": len(value), "large_prose_min_words": 12}
        ),
    )
    assert (
        scan(
            source,
            POLICY.model_copy(
                update={
                    "large_prose_min_chars": len(value) + 1,
                    "large_prose_min_words": 12,
                }
            ),
        )
        == []
    )
    assert (
        scan(
            source,
            POLICY.model_copy(
                update={
                    "large_prose_min_chars": len(value),
                    "large_prose_min_words": 13,
                }
            ),
        )
        == []
    )


def test_only_test_functions_and_methods_use_expected_aliases() -> None:
    source = (
        f"EXPECTED = {NARRATIVE!r}\n"
        "def helper():\n assert render() == EXPECTED\n"
        "class TestReport:\n"
        f" def test_report(self):\n  expected = {NARRATIVE!r}\n  assert render() == expected\n"
        "def test_module_alias():\n assert render() == EXPECTED\n"
    )
    assert scan(source) == [
        ("alphus/python/none/testing/large-prose-assertion", 7),
        ("alphus/python/none/testing/large-prose-assertion", 9),
    ]


def test_local_binding_and_parameters_shadow_module_expected_constants() -> None:
    source = (
        f"EXPECTED = {NARRATIVE!r}\n"
        "def test_local():\n EXPECTED = generated()\n assert render() == EXPECTED\n"
        "def test_parameter(EXPECTED):\n assert render() == EXPECTED\n"
        "def test_future_local():\n assert render() == EXPECTED\n EXPECTED = generated()\n"
    )
    assert scan(source) == []


def test_rebinding_a_text_alias_or_nested_scope_does_not_leak() -> None:
    source = (
        f"def test_report():\n expected = {NARRATIVE!r}\n"
        " expected = build_expected()\n assert render() == expected\n"
        " def helper():\n"
        f"  nested = {NARRATIVE!r}\n  assert render() == nested\n"
        " assert render() == nested\n"
    )
    assert scan(source) == []


def test_configured_plan_reads_and_existence_checks_warn_without_opening_files() -> (
    None
):
    source = (
        "from pathlib import Path as File\n"
        "def test_plan():\n"
        " plan = File('docs') / 'plans' / 'missing.md'\n"
        " alias = plan\n"
        " text = alias.read_text()\n"
        " assert plan.exists()\n"
        " with open('PLAN.md', encoding='utf-8') as stream:\n  assert stream.read()\n"
    )
    assert scan(source) == [
        ("alphus/python/none/testing/ephemeral-plan-dependency", 5),
        ("alphus/python/none/testing/ephemeral-plan-dependency", 6),
        ("alphus/python/none/testing/ephemeral-plan-dependency", 7),
    ]


def test_module_file_root_and_pathlib_module_aliases_resolve_statically() -> None:
    source = (
        "import pathlib as files\n"
        "ROOT = files.Path(__file__).resolve().parents[1]\n"
        "def test_plan():\n"
        " plan = ROOT / 'docs/plans/closure.md'\n"
        " assert plan.is_file()\n"
    )
    assert scan(source) == [("alphus/python/none/testing/ephemeral-plan-dependency", 5)]


@pytest.mark.parametrize("mode", ["r", "rb", "r+"])
def test_read_modes_use_builtin_and_path_open(mode: str) -> None:
    source = (
        "from pathlib import Path\n"
        "from io import open as read_file\n"
        f"def test_plan():\n read_file('PLAN.md', {mode!r})\n Path('PLAN.md').open(mode={mode!r})\n"
    )
    assert scan(source) == [
        ("alphus/python/none/testing/ephemeral-plan-dependency", 4),
        ("alphus/python/none/testing/ephemeral-plan-dependency", 5),
    ]


def test_module_open_alias_and_file_keyword_are_recognized() -> None:
    source = (
        "import io as streams\n"
        "def test_plan():\n"
        " streams.open(file='PLAN.md', mode='rb')\n"
        " open(file='PLAN.md')\n"
    )
    assert scan(source) == [
        ("alphus/python/none/testing/ephemeral-plan-dependency", 3),
        ("alphus/python/none/testing/ephemeral-plan-dependency", 4),
    ]


def test_plan_writes_temporary_paths_and_same_test_fixtures_are_not_dependencies() -> (
    None
):
    source = (
        "from pathlib import Path\n"
        "def test_plan(tmp_path, tmpdir):\n"
        " temporary = tmp_path / 'docs/plans/fixture.md'\n"
        " alias = temporary\n alias.read_text()\n"
        " (tmpdir / 'PLAN.md').exists()\n"
        " plan = Path('docs/plans/fixture.md')\n"
        " plan.write_text('test fixture')\n assert plan.read_text()\n"
        " with open('PLAN.md', 'w') as stream:\n  stream.write('fixture')\n"
        " assert Path('PLAN.md').exists()\n"
    )
    assert scan(source) == []


def test_read_before_fixture_creation_is_still_a_dependency() -> None:
    source = (
        "from pathlib import Path\n"
        "def test_plan():\n plan = Path('PLAN.md')\n plan.read_bytes()\n"
        " plan.write_bytes(b'fixture')\n plan.read_bytes()\n"
    )
    assert scan(source) == [("alphus/python/none/testing/ephemeral-plan-dependency", 4)]


def test_read_used_as_a_write_argument_is_observed_before_fixture_creation() -> None:
    source = (
        "from pathlib import Path\n"
        "def test_plan():\n"
        " Path('PLAN.md').write_text(Path('PLAN.md').read_text())\n"
        " Path('PLAN.md').read_text()\n"
    )
    assert scan(source) == [("alphus/python/none/testing/ephemeral-plan-dependency", 3)]


def test_stable_documents_strings_dynamic_paths_and_empty_patterns_are_ignored() -> (
    None
):
    source = (
        "from pathlib import Path\n"
        "def test_docs():\n"
        " assert Path('README.md').read_text()\n"
        " assert Path('docs/schema.json').is_file()\n"
        " assert scanner('docs/plans/session.md') == []\n"
        " assert Path(document_name()).read_text()\n"
        " assert helper('docs/plans/session.md')\n"
    )
    assert scan(source) == []
    assert (
        scan(
            "def test_plan():\n open('PLAN.md')\n",
            POLICY.model_copy(update={"ephemeral_document_patterns": ()}),
        )
        == []
    )


def test_rebinding_or_shadowing_open_path_and_plan_names_prevents_stale_resolution() -> (
    None
):
    source = (
        "from pathlib import Path\n"
        "def test_shadow(open):\n open('PLAN.md')\n"
        "def test_rebind():\n"
        " plan = Path('PLAN.md')\n plan = dynamic_path()\n plan.read_text()\n"
        " Path = custom_path\n Path('PLAN.md').read_text()\n"
        "def test_local_binding():\n open('PLAN.md')\n open = custom_open\n"
    )
    assert scan(source) == []


def test_branch_created_fixture_is_not_assumed_to_exist_on_every_path() -> None:
    source = (
        "from pathlib import Path\n"
        "def test_plan():\n plan = Path('PLAN.md')\n"
        " if create_fixture:\n  plan.write_text('fixture')\n"
        " assert plan.read_text()\n"
    )
    assert scan(source) == [("alphus/python/none/testing/ephemeral-plan-dependency", 6)]


def test_class_members_do_not_replace_method_global_bindings() -> None:
    source = (
        "from pathlib import Path\n"
        "class TestGlobal:\n"
        " Path = custom_path\n"
        " def test_plan(self):\n  Path('PLAN.md').read_text()\n"
        "class TestClassImport:\n"
        " from pathlib import Path as LocalPath\n"
        " def test_plan(self):\n  LocalPath('PLAN.md').read_text()\n"
    )
    assert scan(source) == [("alphus/python/none/testing/ephemeral-plan-dependency", 5)]


def test_file_scope_and_exclusions_are_respected(tmp_path: Path) -> None:
    for relative in (
        "tests/test_plan.py",
        "tests/ignored/test_plan.py",
        "src/plans.py",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_plan():\n open('PLAN.md')\n", encoding="utf-8")
    policy = POLICY.model_copy(update={"exclude": ("tests/ignored/**",)})
    findings = check_test_quality(
        tmp_path,
        [
            Path("src/plans.py"),
            Path("tests/ignored/test_plan.py"),
            Path("tests/test_plan.py"),
        ],
        policy,
    )
    assert [
        (item.path, item.line, item.rule_id, item.severity) for item in findings
    ] == [
        (
            "tests/test_plan.py",
            2,
            "alphus/python/none/testing/ephemeral-plan-dependency",
            "warning",
        )
    ]


def test_multiple_same_line_findings_are_deterministic() -> None:
    source = "def test_plan():\n open('PLAN.md'); open('docs/plans/a.md')\n"
    first = python_findings(source, "tests/test_plan.py", POLICY)
    second = python_findings(source, "tests/test_plan.py", POLICY)
    assert first == second
    assert [item.message for item in first] == sorted(item.message for item in first)
