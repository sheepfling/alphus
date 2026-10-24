"""Typed bindings retain native diagnostics while sharing intent rollups."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from alphus.config import load_config
from alphus.contracts.findings import (
    Diagnostic,
    FindingRollups,
    deduplicate_semantic_diagnostics,
)
from alphus.contracts.rule_tags import Category, Scope
from alphus.policy.intents import (
    NATIVE_RULE_BINDINGS,
    CommonIntent,
    NativeIntentContextError,
    NativeRuleResolution,
    NativeToolContext,
    VersionPolicy,
    bind_native_diagnostic,
    binding_for_native_rule,
    resolve_native_rule_selection,
    validate_native_context,
)


def ruff_context(**overrides: object) -> NativeToolContext:
    return NativeToolContext.model_validate(
        {
            "backend": "ruff",
            "executable_available": True,
            "version": "0.16.1",
            **overrides,
        }
    )


def test_catalog_maps_distinct_native_rules_without_claiming_equivalence() -> None:
    pairs = {
        (binding.intent, language)
        for binding in NATIVE_RULE_BINDINGS
        if binding.status == "partial"
        for language in binding.languages
    }
    assert (CommonIntent.NAMING, Scope.PYTHON) in pairs
    assert (CommonIntent.NAMING, Scope.CPP) in pairs
    assert (CommonIntent.NAMING, Scope.JAVASCRIPT) in pairs
    assert (CommonIntent.UNUSED, Scope.PYTHON) in pairs
    assert (CommonIntent.UNUSED, Scope.CPP) in pairs
    assert (CommonIntent.UNUSED, Scope.TYPESCRIPT) in pairs
    assert (CommonIntent.UNREACHABLE, Scope.PYTHON) in pairs
    assert (CommonIntent.UNREACHABLE, Scope.CPP) in pairs
    assert (CommonIntent.UNREACHABLE, Scope.JAVASCRIPT) in pairs
    assert (CommonIntent.UNREACHABLE, Scope.TYPESCRIPT) in pairs

    assert binding_for_native_rule("ruff", "F401", Scope.PYTHON) is not None
    assert all(
        binding_for_native_rule("ruff", f"ARG00{number}", Scope.PYTHON) is not None
        for number in range(1, 6)
    )
    assert binding_for_native_rule("ruff", "W0101", Scope.PYTHON) is None
    ruff_unreachable = next(
        binding
        for binding in NATIVE_RULE_BINDINGS
        if binding.key == "python.unreachable.ruff"
    )
    assert ruff_unreachable.status == "unsupported"
    assert ruff_unreachable.version_policy is VersionPolicy.VERIFIED_RANGE
    assert binding_for_native_rule("tsc", "7027", Scope.TYPESCRIPT) is not None


def test_native_mapping_adds_typed_category_without_changing_wire_fields() -> None:
    binding = binding_for_native_rule("ruff", "F401", Scope.PYTHON)
    assert binding is not None
    native = Diagnostic(
        source="ruff",
        rule_id="F401",
        message="unused import: legacy_api",
        severity="error",
        path="src/package.py",
        line=3,
    )

    mapped = bind_native_diagnostic(native, binding, Scope.PYTHON, ruff_context())

    assert mapped.source == native.source
    assert mapped.rule_id == native.rule_id
    assert mapped.message == native.message
    assert mapped.path == native.path
    assert mapped.line == native.line
    assert mapped.severity == "warning"
    assert mapped.matches_category(Category.MAINTAINABILITY)
    assert not mapped.matches_category(Category.STYLE)
    assert mapped.to_wire() == {
        "source": "ruff",
        "rule_id": "F401",
        "message": "unused import: legacy_api",
        "severity": "warning",
        "path": "src/package.py",
        "line": 3,
        "priority": None,
    }

    rollups = FindingRollups.from_diagnostics((mapped,))
    assert [(row.key, row.count) for row in rollups.categories] == [
        ("maintainability", 1)
    ]


def test_matching_shared_finding_is_deduplicated_in_favor_of_native_evidence() -> None:
    binding = binding_for_native_rule("ruff", "F401", Scope.PYTHON)
    assert binding is not None
    native = bind_native_diagnostic(
        Diagnostic(
            source="ruff",
            rule_id="F401",
            message="unused import: legacy_api",
            path="src/package.py",
            line=3,
        ),
        binding,
        Scope.PYTHON,
        ruff_context(),
    )
    shared = Diagnostic(
        source="alphus",
        rule_id=binding.rule_tag(Scope.PYTHON).rule_id,
        message=native.message,
        severity="error",
        path=native.path,
        line=native.line,
    )

    deduplicated = deduplicate_semantic_diagnostics((shared, native))

    assert len(deduplicated) == 1
    assert deduplicated[0].source == "ruff"
    assert deduplicated[0].rule_id == "F401"
    assert deduplicated[0].severity == "error"
    assert FindingRollups.from_diagnostics((shared, native)).categories[0].count == 1


def test_distinct_native_rule_ids_and_evidence_are_not_collapsed() -> None:
    ruff = binding_for_native_rule("ruff", "F401", Scope.PYTHON)
    pylint = binding_for_native_rule("pylint", "W0611", Scope.PYTHON)
    assert ruff is not None and pylint is not None
    message = "unused import: legacy_api"
    native_ruff = bind_native_diagnostic(
        Diagnostic(source="ruff", rule_id="F401", message=message, path="x.py", line=1),
        ruff,
        Scope.PYTHON,
        ruff_context(),
    )
    native_pylint = bind_native_diagnostic(
        Diagnostic(
            source="pylint", rule_id="W0611", message=message, path="x.py", line=1
        ),
        pylint,
        Scope.PYTHON,
        NativeToolContext(backend="pylint", executable_available=True, version="4.1.3"),
    )
    other_evidence = Diagnostic(
        source="alphus",
        rule_id=ruff.rule_tag(Scope.PYTHON).rule_id,
        message="different native evidence",
        path="x.py",
        line=1,
    )

    result = deduplicate_semantic_diagnostics(
        (native_ruff, native_pylint, other_evidence)
    )
    assert [item.rule_id for item in result] == [
        "F401",
        "W0611",
        other_evidence.rule_id,
    ]


def test_native_context_rejects_missing_tools_versions_and_parse_failures() -> None:
    binding = binding_for_native_rule("ruff", "F401", Scope.PYTHON)
    assert binding is not None
    with pytest.raises(NativeIntentContextError, match="unavailable"):
        validate_native_context(binding, ruff_context(executable_available=False))
    with pytest.raises(NativeIntentContextError, match="no version"):
        validate_native_context(binding, ruff_context(version=None))
    with pytest.raises(NativeIntentContextError, match="syntax errors"):
        validate_native_context(
            binding, ruff_context(syntax_errors=("file.py: invalid syntax",))
        )
    with pytest.raises(NativeIntentContextError, match="compile database"):
        binding = binding_for_native_rule(
            "clang-tidy", "readability-identifier-naming", Scope.CPP
        )
        assert binding is not None
        validate_native_context(
            binding,
            NativeToolContext(
                backend="clang-tidy",
                executable_available=True,
                version="18.1.0",
                compiler_version="18.1.0",
            ),
        )
    compiler_binding = binding_for_native_rule("clang", "-Wunused-parameter", Scope.CPP)
    assert compiler_binding is not None
    with pytest.raises(NativeIntentContextError, match="effective compiler arguments"):
        validate_native_context(
            compiler_binding,
            NativeToolContext(
                backend="clang",
                executable_available=True,
                version="18.1.0",
                compiler_version="18.1.0",
            ),
        )


def test_tool_context_version_and_compiler_must_match() -> None:
    binding = binding_for_native_rule(
        "clang-tidy", "readability-identifier-naming", Scope.CPP
    )
    assert binding is not None
    context = NativeToolContext(
        backend="clang-tidy",
        executable_available=True,
        version="18.1.0",
        compiler_version="19.0.0",
        compiler_arguments=("-std=c++20",),
        compile_database_available=True,
    )
    with pytest.raises(NativeIntentContextError, match="versions do not match"):
        validate_native_context(binding, context)


def test_compiler_diagnostic_requires_matching_build_context() -> None:
    binding = binding_for_native_rule("clang", "-Wunused-parameter", Scope.CPP)
    assert binding is not None
    context = NativeToolContext(
        backend="clang",
        executable_available=True,
        version="18.1.0",
        compiler_version="18.1.0",
        compiler_arguments=("-std=c++20", "-Wextra", "-Wunused-parameter"),
    )

    validate_native_context(binding, context)


def test_typescript_unreachable_requires_explicit_compiler_option() -> None:
    binding = binding_for_native_rule("tsc", "7027", Scope.TYPESCRIPT)
    assert binding is not None
    context = NativeToolContext(
        backend="tsc",
        executable_available=True,
        version="5.9.3",
        compiler_arguments=("--project", "tsconfig.json"),
    )
    with pytest.raises(NativeIntentContextError, match="allowUnreachableCode=false"):
        validate_native_context(binding, context)

    configured_context = NativeToolContext(
        backend="tsc",
        executable_available=True,
        version="5.9.3",
        compiler_arguments=("--project", "tsconfig.json"),
        effective_settings=("allowUnreachableCode=false",),
    )
    mapped = bind_native_diagnostic(
        Diagnostic(
            source="tsc",
            rule_id="7027",
            message="Unreachable code detected",
            path="src/sample.ts",
            line=4,
        ),
        binding,
        Scope.TYPESCRIPT,
        configured_context,
    )
    assert mapped.severity == "warning"
    assert mapped.matches_category(Category.CORRECTNESS)


def test_typescript_eslint_requires_observed_plugin_versions() -> None:
    binding = binding_for_native_rule(
        "eslint", "@typescript-eslint/no-unused-vars", Scope.TYPESCRIPT
    )
    assert binding is not None
    context = NativeToolContext(
        backend="eslint",
        executable_available=True,
        version="10.13.0",
    )
    with pytest.raises(
        NativeIntentContextError, match="plugin versions are unavailable"
    ):
        validate_native_context(binding, context)

    configured_context = NativeToolContext(
        backend="eslint",
        executable_available=True,
        version="10.13.0",
        plugin_versions=(
            ("@typescript-eslint/parser", "8.72.0"),
            ("@typescript-eslint/eslint-plugin", "8.72.0"),
        ),
    )
    mapped = bind_native_diagnostic(
        Diagnostic(
            source="eslint",
            rule_id="@typescript-eslint/no-unused-vars",
            message="Unused type-only import",
            path="src/sample.ts",
            line=1,
        ),
        binding,
        Scope.TYPESCRIPT,
        configured_context,
    )
    assert mapped.matches_category(Category.MAINTAINABILITY)


def test_ruff_native_intent_fixtures_preserve_supported_evidence(
    pytestconfig: pytest.Config,
) -> None:
    root = pytestconfig.rootpath
    fixtures = root / "tests/fixtures/native_intents/python"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--isolated",
            "--ignore-noqa",
            "--select",
            "F401,F841,ARG001,N801,N802,N803,N804,N805,N806,N807,N811,N812,"
            "N813,N814,N815,N816,N817,N818,N999",
            "--config",
            'lint.dummy-variable-rgx = "^_"',
            "--config",
            'lint.pep8-naming.ignore-names = ["legacy_name"]',
            "--exclude",
            "generated",
            "--output-format",
            "json",
            str(fixtures),
        ],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert isinstance(report, list)
    codes = {finding["code"] for finding in report}
    assert {"F401", "F841", "ARG001", "N801", "N802"} <= codes
    assert all("unreachable" not in finding["message"].lower() for finding in report)

    paths = {root.joinpath(finding["filename"]).resolve() for finding in report}
    assert paths == {fixtures / "negative.py"}
    ruff_version = subprocess.run(
        [sys.executable, "-m", "ruff", "--version"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.split()[-1]
    mapped = []
    for finding in report:
        binding = binding_for_native_rule("ruff", finding["code"], Scope.PYTHON)
        assert binding is not None
        mapped.append(
            bind_native_diagnostic(
                Diagnostic(
                    source="ruff",
                    rule_id=finding["code"],
                    message=finding["message"],
                    path=str(Path(finding["filename"]).relative_to(root)),
                    line=finding["location"]["row"],
                    severity="error",
                ),
                binding,
                Scope.PYTHON,
                ruff_context(version=ruff_version),
            )
        )
    assert all(finding.severity == "warning" for finding in mapped)
    assert {finding.tag.category for finding in mapped if finding.tag} == {
        Category.STYLE,
        Category.MAINTAINABILITY,
    }


def test_clang_fixture_requires_and_preserves_observed_build_context(
    pytestconfig: pytest.Config,
) -> None:
    compiler = shutil.which("clang++")
    if compiler is None:
        pytest.skip("clang++ is unavailable; no compiler tool is installed by tests")
    identity = subprocess.run(
        [compiler, "--version"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    if "clang" not in identity.lower():
        pytest.skip("clang++ resolves to a different compiler")
    version = subprocess.run(
        [compiler, "-dumpversion"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    flags = (
        "-fsyntax-only",
        "-std=c++20",
        "-Wunused-variable",
        "-Wunused-function",
        "-Wunused-parameter",
        "-Wunreachable-code",
    )
    fixture = pytestconfig.rootpath / "tests/fixtures/native_intents/cpp/negative.cpp"
    result = subprocess.run(
        [compiler, *flags, str(fixture)],
        cwd=pytestconfig.rootpath,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    positive_fixture = (
        pytestconfig.rootpath / "tests/fixtures/native_intents/cpp/positive.cpp"
    )
    positive_result = subprocess.run(
        [compiler, *flags, str(positive_fixture)],
        cwd=pytestconfig.rootpath,
        capture_output=True,
        check=False,
        text=True,
    )
    assert positive_result.returncode == 0
    assert positive_result.stderr == ""
    diagnostics = re.findall(
        r"^(.+):(\d+):\d+: warning: (.+) \[(-W[^\]]+)\]$",
        result.stderr,
        flags=re.MULTILINE,
    )
    assert diagnostics

    context = NativeToolContext(
        backend="clang",
        executable_available=True,
        version=version,
        compiler_version=version,
        compiler_arguments=flags,
    )
    mapped = []
    for path, line, message, native_rule in diagnostics:
        binding = binding_for_native_rule("clang", native_rule, Scope.CPP)
        if binding is None:
            continue
        mapped.append(
            bind_native_diagnostic(
                Diagnostic(
                    source="clang",
                    rule_id=native_rule,
                    message=message,
                    path=str(Path(path).relative_to(pytestconfig.rootpath)),
                    line=int(line),
                ),
                binding,
                Scope.CPP,
                context,
            )
        )
    assert {finding.rule_id for finding in mapped} >= {
        "-Wunused-variable",
        "-Wunused-function",
        "-Wunused-parameter",
        "-Wunreachable-code",
    }
    assert all(finding.severity == "warning" for finding in mapped)


def test_binding_does_not_rewrite_consumer_native_configuration(
    pytestconfig: pytest.Config,
) -> None:
    root = pytestconfig.rootpath
    config = load_config(root / "examples/polyglot/quality-gates.toml")
    before = config.model_dump()
    native_config = root / "examples/consumer/fastapi/ruff.fastapi.toml"
    native_config_before = native_config.read_bytes()
    binding = binding_for_native_rule("ruff", "F401", Scope.PYTHON)
    assert binding is not None
    bind_native_diagnostic(
        Diagnostic(source="ruff", rule_id="F401", message="unused import"),
        binding,
        Scope.PYTHON,
        ruff_context(),
    )
    assert config.model_dump() == before
    assert native_config.read_bytes() == native_config_before


def test_consumer_setting_wins_and_opted_in_conflicts_are_visible() -> None:
    binding = binding_for_native_rule("ruff", "F401", Scope.PYTHON)
    assert binding is not None

    consumer_owned = resolve_native_rule_selection(
        binding,
        consumer_enabled=False,
        shared_enabled=True,
    )
    assert consumer_owned == NativeRuleResolution(
        effective_enabled=False,
        source="consumer",
        conflict=False,
        message="The consumer's native-tool setting remains authoritative.",
    )

    conflict = resolve_native_rule_selection(
        binding,
        consumer_enabled=False,
        shared_enabled=True,
        shared_policy_opt_in=True,
    )
    assert conflict.effective_enabled is False
    assert conflict.source == "conflict"
    assert conflict.conflict
    assert "consumer setting wins" in conflict.message

    opted_in = resolve_native_rule_selection(
        binding,
        consumer_enabled=None,
        shared_enabled=True,
        shared_policy_opt_in=True,
    )
    assert opted_in.effective_enabled is True
    assert opted_in.source == "shared-policy"
