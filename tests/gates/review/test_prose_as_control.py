import re
from pathlib import Path

import pytest

from alphus.config import ProseAsControlPolicy
from alphus.gates.review.prose_as_control import (
    check_lossy_text_rewrite,
    check_prose_as_control,
    lossy_rewrite_lines,
    prose_control_literals,
)

_SENTENCE = (
    "Source-derived normative statement retained at clause scope; "
    "no modeled transition was asserted."
)


def _policy(**overrides: object) -> ProseAsControlPolicy:
    return ProseAsControlPolicy(
        extensions=(".py",), source_paths=("src/render/*.py",), **overrides
    )


def test_reports_long_prose_literal_used_as_branch_discriminator() -> None:
    source = f'if note == "{_SENTENCE}":\n    suppress_note()\n'
    assert prose_control_literals(source, _policy()) == [(1, _SENTENCE)]


def test_ignores_short_protocol_text_and_prose_only_in_output() -> None:
    source = f'''\
if response == "OK":
    accept()
message = "{_SENTENCE}"
'''
    assert prose_control_literals(source, _policy()) == []


def test_allowlist_preserves_known_protocol_or_compatibility_literals() -> None:
    source = f'if note == "{_SENTENCE}":\n    preserve()\n'
    assert not prose_control_literals(source, _policy(allowed_literals=(_SENTENCE,)))


@pytest.mark.parametrize("separator", ["\n", "\r"])
def test_allowlist_accepts_exact_multiline_protocol_literals(separator: str) -> None:
    literal = (
        "The remote peer reports a state transition"
        f"{separator}that this client does not handle and needs review."
    )
    source = f"if note == {literal!r}:\n    preserve()\n"

    assert prose_control_literals(source, _policy(allowed_literals=(literal,))) == []


def test_allowlist_rejects_empty_literal() -> None:
    with pytest.raises(ValueError, match="allowed prose literals must be non-empty"):
        _policy(allowed_literals=("",))


def test_only_branch_comparisons_are_reported() -> None:
    source = f'result = note == "{_SENTENCE}"\n'
    assert prose_control_literals(source, _policy()) == []


def test_scans_only_declared_paths_and_respects_exclusions(tmp_path: Path) -> None:
    source = tmp_path / "src/render/report.py"
    source.parent.mkdir(parents=True)
    source.write_text(f'if note == "{_SENTENCE}":\n    pass\n', encoding="utf-8")

    findings = check_prose_as_control(
        tmp_path, [Path("src/render/report.py")], _policy()
    )
    assert len(findings) == 1
    assert findings[0].path == "src/render/report.py"
    assert findings[0].line == 1
    assert "does not imply AI authorship" in findings[0].message

    excluded = _policy(exclude=("src/render/**",))
    assert not check_prose_as_control(
        tmp_path, [Path("src/render/report.py")], excluded
    )


def test_lossy_text_rewrite_matches_configured_number_erasure_only() -> None:
    source = """\
import re
cleaned = re.sub(r"(?<!\\S)\\d{1,3}\\.\\d{2}(?!\\S)", " ", prose)
trimmed = prose.strip()
kept = re.sub(r"\\s+", " ", prose)
"""
    configured = _policy(lossy_text_rewrite=True, regex_sub_helpers=("re.sub",))
    assert lossy_rewrite_lines(source, configured) == [
        (2, r"(?<!\S)\d{1,3}\.\d{2}(?!\S)")
    ]
    assert (
        lossy_rewrite_lines(
            source, _policy(lossy_text_rewrite=True, regex_sub_helpers=("regex.sub",))
        )
        == []
    )


def test_lossy_regex_rewrite_ignores_zero_width_digit_assertions() -> None:
    source = r"""\
zero_width = re.sub(r"(?=\d)", "", text)
lookbehind = re.sub(r"(?<=\d)", " ", text)
escaped = re.sub(r"\\d", "", text)
negated = re.sub(r"[^\d]+", "", text)
consuming = re.sub(r"(?=\d)\d+", "", text)
"""

    assert lossy_rewrite_lines(
        source, _policy(lossy_text_rewrite=True, regex_sub_helpers=("re.sub",))
    ) == [(6, r"(?=\d)\d+")]


def test_lossy_regex_rewrite_preserves_verbose_brace_semantics() -> None:
    source = r'''\
zero_count = re.sub(r"\d{0}", "", text)
zero_range = re.sub(r"\d{0,0}", " ", text)
verbose_zero_count = re.sub(r"(?x)\d{ 0 }", "", text)
verbose_zero_range = re.sub(r"(?x)\d{0, 0}", " ", text)
verbose_actual_zero_count = re.sub(r"(?x)\d{0}", "", text)
verbose_actual_zero_range = re.sub(r"(?x)\d{0,0}", " ", text)
verbose_comment = re.sub(r"""(?x)# \d is only a comment
\s+""", "", text)
actual_digit_consumer = re.sub(r"""(?x)# \d is a comment
\d+""", "", text)
'''

    assert lossy_rewrite_lines(
        source, _policy(lossy_text_rewrite=True, regex_sub_helpers=("re.sub",))
    ) == [
        (4, "(?x)\\d{ 0 }"),
        (5, "(?x)\\d{0, 0}"),
        (10, "(?x)# \\d is a comment\n\\d+"),
    ]

    assert re.sub(r"(?x)\d{ 0 }", "", "7{0}") == ""
    assert re.sub(r"(?x)\d{0}", "", "7{0}") == "7{0}"


def test_lossy_text_rewrite_detects_literal_semantic_token_deletion() -> None:
    source = """\
cleaned = prose.replace("0.25", "")
signless = prose.replace("-", " ")
words = prose.replace("tolerance", "")
spacing = prose.replace(" ", "")
kept = prose.replace("0.25", "value")
"""

    assert lossy_rewrite_lines(source, _policy(lossy_text_rewrite=True)) == [
        (1, "replace('0.25', '')"),
        (2, "replace('-', ' ')"),
    ]


def test_lossy_text_rewrite_respects_declared_scope_and_exclusions(
    tmp_path: Path,
) -> None:
    target = tmp_path / "src/render/cleanup.py"
    target.parent.mkdir(parents=True)
    target.write_text('cleaned = prose.replace("0.25", "")\n', encoding="utf-8")
    policy = _policy(lossy_text_rewrite=True, exclude=("src/render/generated/**",))

    assert (
        len(check_lossy_text_rewrite(tmp_path, [Path("src/render/cleanup.py")], policy))
        == 1
    )
    assert not check_lossy_text_rewrite(
        tmp_path, [Path("src/render/generated/cleanup.py")], policy
    )
    assert not check_lossy_text_rewrite(tmp_path, [Path("tests/cleanup.py")], policy)


def test_lossy_text_rewrite_handles_literal_replace_counts() -> None:
    source = """\
one = prose.replace("0.25", "", 1)
all = prose.replace("0.25", "", -1)
keyword = prose.replace("-", " ", count=1)
zero = prose.replace("0.25", "", 0)
unknown = prose.replace("0.25", "", count=limit)
"""

    assert lossy_rewrite_lines(source, _policy(lossy_text_rewrite=True)) == [
        (1, "replace('0.25', '', count=1)"),
        (2, "replace('0.25', '', count=-1)"),
        (3, "replace('-', ' ', count=1)"),
    ]


def test_lossy_text_rewrite_does_not_claim_receiver_is_a_string(
    tmp_path: Path,
) -> None:
    target = tmp_path / "src/render/custom_api.py"
    target.parent.mkdir(parents=True)
    target.write_text("result = registry.replace('0.25', '')\n", encoding="utf-8")

    findings = check_lossy_text_rewrite(
        tmp_path,
        [Path("src/render/custom_api.py")],
        _policy(lossy_text_rewrite=True),
    )
    assert len(findings) == 1
    assert "receiver type is not inferred" in findings[0].message


def test_lossy_text_rewrite_allowance_is_exactly_scoped(tmp_path: Path) -> None:
    target = tmp_path / "src/render/cleanup.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "comma = options.replace(',', ' ')\nnumber = prose.replace('0.25', '')\n",
        encoding="utf-8",
    )
    other = tmp_path / "src/render/other.py"
    other.write_text("comma = options.replace(',', ' ')\n", encoding="utf-8")
    policy = _policy(
        lossy_text_rewrite=True,
        allowed_literal_rewrites=(
            {"path": "src/render/cleanup.py", "expression": "replace(',', ' ')"},
        ),
    )

    findings = check_lossy_text_rewrite(
        tmp_path,
        [Path("src/render/cleanup.py"), Path("src/render/other.py")],
        policy,
    )
    assert [(finding.path, finding.line) for finding in findings] == [
        ("src/render/cleanup.py", 2),
        ("src/render/other.py", 1),
    ]


def test_lossy_text_rewrite_allowance_rejects_duplicate_scopes() -> None:
    with pytest.raises(
        ValueError, match="allowed literal rewrite scopes must be unique"
    ):
        _policy(
            lossy_text_rewrite=True,
            allowed_literal_rewrites=(
                {
                    "path": "src/render/cleanup.py",
                    "expression": "replace(',', ' ')",
                },
                {
                    "path": "src/render/cleanup.py",
                    "expression": "replace(',', ' ')",
                },
            ),
        )


def test_lossy_text_rewrite_requires_explicit_regex_helpers_and_reports_evidence(
    tmp_path: Path,
) -> None:
    _policy(lossy_text_rewrite=True)
    target = tmp_path / "src/render/cleanup.py"
    target.parent.mkdir(parents=True)
    target.write_text('import re\nre.sub(r"\\d+", "", prose)\n', encoding="utf-8")
    findings = check_lossy_text_rewrite(
        tmp_path,
        [Path("src/render/cleanup.py")],
        _policy(lossy_text_rewrite=True, regex_sub_helpers=("re.sub",)),
    )
    assert len(findings) == 1
    assert findings[0].rule_id == "alphus/python/none/correctness/lossy-text-rewrite"
    assert "does not prove" in findings[0].message
