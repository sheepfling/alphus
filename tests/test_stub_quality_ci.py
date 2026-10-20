from __future__ import annotations

import ast
import json
from pathlib import Path

from alphus_stub_quality.api_audit_support import ast_parameters, normalized_type
from alphus_stub_quality.negative_typecheck import (
    check_result,
    expected_error_lines,
    observed_error_lines,
)
from alphus_stub_quality.verify import read_config


def test_negative_fixture_requires_exact_error_lines() -> None:
    source = "from package import Item\nItem(1)  # expect-error\nItem(2)\n"
    expected = expected_error_lines(source)

    assert expected == {2}
    assert observed_error_lines(
        "negative_typecheck.py:2: error: bad argument", "negative_typecheck.py"
    ) == {2}
    assert observed_error_lines(
        "/tmp/negative_typecheck.py:2:5 - error: bad argument",
        "negative_typecheck.py",
    ) == {2}
    assert (
        check_result(
            1,
            "negative_typecheck.py:2: error: bad argument",
            "negative_typecheck.py",
            expected,
        )
        == []
    )
    assert check_result(0, "", "negative_typecheck.py", expected)
    assert check_result(
        1,
        "negative_typecheck.py:2: error: expected\nnegative_typecheck.py:3: error: extra",
        "negative_typecheck.py",
        expected,
    )
    assert (
        check_result(
            1,
            "negative_typecheck.py:2: error: bad argument",
            "negative_typecheck.py",
            set(),
            expected_count=1,
            required_diagnostics=("bad argument",),
        )
        == []
    )
    count_issues = check_result(
        1,
        "negative_typecheck.py:2: error: bad argument",
        "negative_typecheck.py",
        set(),
        expected_count=2,
    )
    assert any("expected 2 error diagnostics, got 1" in issue for issue in count_issues)


def test_api_audit_helpers_normalize_signature_shapes() -> None:
    node = ast.parse(
        "def f(a: int, /, b: str = 'x', *args: bytes, c: bool, **kw: object) -> None: ..."
    ).body[0]
    assert isinstance(node, ast.FunctionDef)
    assert ast_parameters(node) == [
        ("a", "positional-only", None),
        ("b", "positional-or-keyword", "'x'"),
        ("args", "var-positional", None),
        ("c", "keyword-only", None),
        ("kw", "var-keyword", None),
    ]
    left = normalized_type(ast.parse("typing.Iterable[str]", mode="eval").body)
    right = normalized_type(
        ast.parse("collections.abc.Iterable[str]", mode="eval").body
    )
    assert left == right
    scoped = normalized_type(
        ast.parse("Kind", mode="eval").body,
        owner_class="Table",
        scoped_type_names=frozenset({"Kind"}),
    )
    assert scoped == ("name", "Table.Kind")


def test_verification_config_keeps_package_specific_gates_optional(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "stub-quality.json"
    config_path.write_text(
        json.dumps(
            {
                "verification": {
                    "stubtest_module": "mdutils",
                    "stubtest_allowlist": "stubtest-allowlist.txt",
                    "positive_fixture": "tests/typecheck.py",
                    "negative_fixture": "tests/negative_typecheck.py.fixture",
                    "negative_expected_count": 7,
                    "mypy_diagnostics": ['Argument "width"'],
                    "pyright_diagnostics": ["Expected 2 more positional arguments"],
                }
            }
        ),
        encoding="utf-8",
    )

    settings = read_config(tmp_path, config_path)

    assert settings.api_audit_module is None
    assert settings.runtime_smoke_module is None
    assert settings.negative_expected_count == 7
    assert settings.mypy_diagnostics == ('Argument "width"',)
    assert settings.pyright_diagnostics == ("Expected 2 more positional arguments",)
