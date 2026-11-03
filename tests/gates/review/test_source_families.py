import ast
import subprocess
from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path

import pytest

from alphus.config import SourceFamilyPolicy
from alphus.gates.review import source_families
from alphus.gates.review.source_families import source_family_findings


def _write(root: Path, name: str, lines: int = 2) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join("pass" for _ in range(lines)), encoding="utf-8")
    return path.relative_to(root)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_opt_in_git_history_reports_correlated_paths_without_claiming_cause(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    _git(tmp_path, "add", "src")
    _git(tmp_path, "commit", "-qm", "add gateway family")
    commit = _git(tmp_path, "rev-parse", "HEAD")

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(min_family_files=5, git_cochange_evidence=True),
    )

    message = findings[0].message
    assert "bounded Git history evidence enabled" in message
    assert "Observed 1 bounded commit(s) co-changing family paths" in message
    assert commit in message
    assert "correlation only" in message
    assert "does not establish causation, ownership, or responsibility" in message
    assert "filename similarity alone does not establish" in message


def test_git_history_window_without_cochanges_is_explicitly_incomplete(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    _git(tmp_path, "add", "src")
    _git(tmp_path, "commit", "-qm", "add gateway family")
    (tmp_path / "src/gateway_client.py").write_text(
        "changed independently\n", encoding="utf-8"
    )
    _git(tmp_path, "add", "src/gateway_client.py")
    _git(tmp_path, "commit", "-qm", "change one family member")

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            git_cochange_evidence=True,
            max_git_history_commits=1,
        ),
    )

    message = findings[0].message
    assert "No multi-member co-change observed in the 1-commit" in message
    assert "not evidence of independence" in message
    assert "history window may be truncated" in message


def test_git_history_failure_is_explicit_and_not_a_clean_zero(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(min_family_files=5, git_cochange_evidence=True),
    )

    assert "Git co-change evidence incomplete" in findings[0].message
    assert "bounded read-only Git history query failed" in findings[0].message


def test_groups_flat_python_family_as_lexical_only(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py", count)
        for name, count in (
            ("client", 3),
            ("server", 7),
            ("routes", 4),
            ("auth", 5),
            ("cache", 6),
        )
    ]
    independent = _write(tmp_path, "src/independent.py")

    findings = source_family_findings(
        tmp_path,
        [*paths, independent],
        SourceFamilyPolicy(
            min_family_files=5,
            file_length_limits=((".py", 500),),
        ),
    )

    assert len(findings) == 1
    assert findings[0].path == "src"
    assert findings[0].severity == "warning"
    assert "5 of 6 selected sibling source files" in findings[0].message
    assert "3–7" in findings[0].message
    assert "distribution:" in findings[0].message
    assert ".py≤500 lines" in findings[0].message
    assert "lexical-only, low-confidence" in findings[0].message
    assert "not assessed" in findings[0].message
    assert "Coupling" in findings[0].message
    assert "move" not in findings[0].message
    assert "gateway_auth.py (5 lines)" in findings[0].message
    assert "min_family_files=5" in findings[0].message
    assert "min_prefix_characters=4" in findings[0].message
    assert "Scope includes" not in findings[0].message
    assert "include=**/*" in findings[0].message
    assert "exclude=**/vendor/**" in findings[0].message


def test_legitimate_backend_family_stays_a_low_confidence_advisory(
    tmp_path: Path,
) -> None:
    """Matplotlib's platform backends are a review candidate, not a verdict."""
    # Representative names from matplotlib/matplotlib at 5a84a6f. Its backend
    # guide describes these as intentional GUI and file-output implementations.
    paths = [
        _write(tmp_path, f"lib/matplotlib/backends/{stem}.py")
        for stem in (
            "backend_agg",
            "backend_cairo",
            "backend_gtk4",
            "backend_pdf",
            "backend_svg",
        )
    ]
    paths.append(_write(tmp_path, "lib/matplotlib/backends/registry.py"))

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            extensions=(".py",),
            include=("lib/matplotlib/backends/**",),
            min_family_files=5,
            min_prefix_characters=4,
        ),
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "warning"
    assert "Family backend_*" in finding.message
    assert "5 of 6 selected sibling source files" in finding.message
    assert "lexical-only, low-confidence advisory review candidate" in finding.message
    assert "responsibility, and public surface not assessed" in finding.message
    assert "filename similarity alone does not establish an architectural problem" in (
        finding.message
    )


def test_opt_in_python_import_evidence_reports_resolved_edges(tmp_path: Path) -> None:
    paths = []
    for name in ("client", "server", "routes", "auth", "cache"):
        paths.append(
            _write(
                tmp_path,
                f"src/gateway_{name}.py",
                1,
            )
        )
    (tmp_path / "src/gateway_client.py").write_text(
        "from gateway_server import serve\n", encoding="utf-8"
    )
    (tmp_path / "src/gateway_server.py").write_text(
        "from gateway_client import connect\n", encoding="utf-8"
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    assert len(findings) == 1
    assert "2 resolved edge(s) target another family member" in findings[0].message
    assert "src/gateway_client.py:1 → src/gateway_server.py" in findings[0].message
    assert (
        "qualified Protocol/TypedDict declarations are partial syntax evidence only"
        in (findings[0].message)
    )
    assert "No literal module-level __all__ was observed" in findings[0].message


def test_cpp_include_evidence_resolves_only_literal_selected_quoted_targets(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.cpp")
        for name in ("client", "routes", "auth", "cache")
    ]
    paths.append(_write(tmp_path, "src/gateway_server.hpp"))
    paths.append(_write(tmp_path, "src/common.hpp"))
    (tmp_path / "src/gateway_client.cpp").write_text(
        '#include "gateway_server.hpp"\n'
        '#include "common.hpp"\n'
        '#include "outside.hpp"\n'
        "#include HEADER_FROM_BUILD_FLAGS\n"
        "#include <vector>\n",
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5, cpp_include_evidence=True, max_import_edges=1
        ),
    )

    message = findings[0].message
    assert "bounded C/C++ quoted include evidence enabled" in message
    assert "1 resolved edge(s) target another family member" in message
    assert "1 target other selected source files" in message
    assert "1 literal include(s) did not resolve to the selected inventory" in message
    assert "src/gateway_client.cpp:1 → src/gateway_server.hpp" in message
    assert "1 edge(s) omitted by max_import_edges" in message
    assert "conditional activation" in message


def test_cpp_include_evidence_reports_selected_external_family_consumers(
    tmp_path: Path,
) -> None:
    family = [
        _write(tmp_path, f"include/gateway_{name}.hpp")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    (tmp_path / "include/gateway_client.hpp").write_text(
        '#include "gateway_server.hpp"\n', encoding="utf-8"
    )
    consumer = _write(tmp_path, "src/runner.cpp")
    (tmp_path / consumer).write_text(
        '#include "../include/gateway_client.hpp"\n', encoding="utf-8"
    )
    policy = SourceFamilyPolicy(min_family_files=5, cpp_include_evidence=True)

    with_consumer = source_family_findings(tmp_path, [*family, consumer], policy)
    without_consumer = source_family_findings(tmp_path, family, policy)

    assert len(with_consumer) == len(without_consumer) == 1
    message = with_consumer[0].message
    assert "1 resolved edge(s) target another family member" in message
    assert "1 incoming edge(s) from selected external C/C++ files" in message
    assert "incoming src/runner.cpp:1 → include/gateway_client.hpp" in message
    assert "do not prove public ownership or architectural coupling" in message
    assert "0 incoming edge(s) from selected external C/C++ files" in (
        without_consumer[0].message
    )


def test_cpp_include_evidence_ignores_block_comments_and_accepts_trailing_comments(
    tmp_path: Path,
) -> None:
    family = [
        _write(tmp_path, f"include/gateway_{name}.hpp")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    (tmp_path / "include/gateway_client.hpp").write_text(
        "/* ignored directive follows\n"
        '#include "gateway_server.hpp"\n'
        "*/\n"
        '#include "gateway_routes.hpp" // accepted trailing comment\n'
        '#inc/**/lude "gateway_auth.hpp"\n',
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        family,
        SourceFamilyPolicy(min_family_files=5, cpp_include_evidence=True),
    )

    assert len(findings) == 1
    message = findings[0].message
    assert "1 resolved edge(s) target another family member" in message
    assert "member include/gateway_client.hpp:4 → include/gateway_routes.hpp" in message
    assert (
        "member include/gateway_client.hpp:2 → include/gateway_server.hpp"
        not in message
    )
    assert (
        "member include/gateway_client.hpp:5 → include/gateway_auth.hpp" not in message
    )


def test_cpp_include_budget_is_not_spent_without_a_cpp_family(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py", 1)
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    unrelated = _write(tmp_path, "src/unrelated.cpp")
    (tmp_path / unrelated).write_text(" " * 256, encoding="utf-8")

    findings = source_family_findings(
        tmp_path,
        [*paths, unrelated],
        SourceFamilyPolicy(
            min_family_files=5,
            cpp_include_evidence=True,
            max_import_analysis_bytes=32,
        ),
    )

    assert len(findings) == 1
    assert "C/C++ include evidence" not in findings[0].message
    assert "C/C++ file(s) could not be analyzed" not in findings[0].message


def test_cpp_include_evidence_ignores_multiline_raw_string_contents(
    tmp_path: Path,
) -> None:
    family = [
        _write(tmp_path, f"include/gateway_{name}.hpp")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    consumer = _write(tmp_path, "src/consumer.cpp")
    (tmp_path / consumer).write_text(
        'const char *example = R"tag(\n'
        '#include "../include/gateway_client.hpp"\n'
        ')tag";\n'
        '#include "../include/gateway_server.hpp" // actual include\n',
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        [*family, consumer],
        SourceFamilyPolicy(min_family_files=5, cpp_include_evidence=True),
    )

    assert len(findings) == 1
    message = findings[0].message
    assert "1 incoming edge(s)" in message
    assert "incoming src/consumer.cpp:4 → include/gateway_server.hpp" in message
    assert "incoming src/consumer.cpp:2 → include/gateway_client.hpp" not in message


def test_cpp_include_budget_reserves_all_family_cores_before_consumers(
    tmp_path: Path,
) -> None:
    families: list[Path] = []
    for prefix in ("gateway", "storage"):
        members = [
            _write(tmp_path, f"src/{prefix}_{name}.hpp")
            for name in ("client", "server", "routes", "auth", "cache")
        ]
        (tmp_path / f"src/{prefix}_client.hpp").write_text(
            f'#include "{prefix}_server.hpp"\n', encoding="utf-8"
        )
        families.extend(members)
    consumer = _write(tmp_path, "src/00_consumer.cpp")
    (tmp_path / consumer).write_text(" " * 128, encoding="utf-8")
    core_bytes = sum((tmp_path / path).stat().st_size for path in families)

    findings = source_family_findings(
        tmp_path,
        [*families, consumer],
        SourceFamilyPolicy(
            min_family_files=5,
            cpp_include_evidence=True,
            max_import_analysis_bytes=core_bytes,
        ),
    )

    family_findings = [finding for finding in findings if "Family " in finding.message]
    assert len(family_findings) == 2
    assert all(
        "1 resolved edge(s) target another family member" in finding.message
        for finding in family_findings
    )
    assert any(
        "shared C/C++ include byte budget was exhausted" in finding.message
        for finding in findings
    )
    assert any(
        "no clean result can be inferred" in finding.message for finding in findings
    )


def test_cpp_include_budget_exhaustion_is_an_incomplete_scan(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.cpp")
        for name in ("client", "server", "routes", "auth", "cache")
    ]

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            cpp_include_evidence=True,
            max_import_analysis_bytes=1,
        ),
    )

    assert len(findings) == 2
    assert "C/C++ file(s) could not be analyzed" in findings[0].message
    assert "no clean result can be inferred" in findings[0].message


@pytest.mark.skipif(
    any(
        find_spec(module) is None
        for module in (
            "tree_sitter",
            "tree_sitter_javascript",
            "tree_sitter_typescript",
        )
    ),
    reason="install the optional alphus[javascript] parser extra",
)
def test_opt_in_javascript_import_evidence_is_parser_backed_and_conservative(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}{suffix}")
        for name, suffix in (
            ("client", ".ts"),
            ("server", ".ts"),
            ("routes", ".tsx"),
            ("auth", ".js"),
            ("cache", ".js"),
            ("common", ".js"),
        )
    ]
    (tmp_path / "src/gateway_client.ts").write_text(
        'import { serve } from "./gateway_server";\n'
        'export { route } from "./gateway_routes";\n'
        'const cache = require("./gateway_cache");\n'
        'const dynamic = import("./missing");\n'
        'import type { Shared } from "@types/shared";\n',
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            javascript_import_evidence=True,
            max_import_edges=2,
        ),
    )

    assert len(findings) == 1
    message = findings[0].message
    assert "bounded JavaScript/TypeScript import evidence enabled" in message
    assert "3 resolved edge(s) target another family member" in message
    assert "2 reference(s) did not resolve uniquely" in message
    assert "src/gateway_client.ts:1 → src/gateway_server.ts" in message
    assert "1 edge(s) omitted by max_import_edges" in message
    assert "TypeScript path aliases" in message
    assert "shadowed require" in message


@pytest.mark.skipif(
    any(
        find_spec(module) is None
        for module in (
            "tree_sitter",
            "tree_sitter_javascript",
            "tree_sitter_typescript",
        )
    ),
    reason="install the optional alphus[javascript] parser extra",
)
def test_javascript_import_parse_and_budget_failures_are_incomplete(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.js")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    (tmp_path / "src/gateway_client.js").write_text(
        'import "./gateway_server";\nconst broken = ;\n', encoding="utf-8"
    )

    parse_findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(min_family_files=5, javascript_import_evidence=True),
    )
    assert len(parse_findings) == 2
    assert (
        "JavaScript/TypeScript file(s) could not be analyzed"
        in parse_findings[0].message
    )
    assert "no clean result can be inferred" in parse_findings[0].message

    budget_findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            javascript_import_evidence=True,
            max_import_analysis_bytes=1,
        ),
    )
    assert len(budget_findings) == 2
    assert (
        "JavaScript/TypeScript file(s) could not be analyzed"
        in budget_findings[0].message
    )


def test_import_evidence_reports_bounded_literal_module_exports(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    (tmp_path / "src/gateway_client.py").write_text(
        "__all__ = ['Client', 'connect', 'Gateway']\n", encoding="utf-8"
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
            max_public_api_names=2,
        ),
    )

    message = findings[0].message
    assert "src/gateway_client.py:1 exports Client" in message
    assert "src/gateway_client.py:1 exports connect" in message
    assert "1 declared name(s) omitted by max_public_api_names" in message
    assert "consumers outside the selected Python inventory" in message


def test_python_package_init_reports_bounded_namespace_import_candidates(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    init = _write(tmp_path, "src/gateway/__init__.py")
    paths.append(init)
    (tmp_path / "src/gateway/gateway_client.py").write_text(
        "class GatewayClient: ...\n", encoding="utf-8"
    )
    (tmp_path / "src/gateway/__init__.py").write_text(
        "from .gateway_client import GatewayClient as PublicClient\n"
        "from .gateway_server import GatewayServer\n"
        "def lazy_import():\n"
        "    from .gateway_routes import Routes\n"
        "    return Routes\n"
        "__all__ = ['PublicClient', 'GatewayServer']\n",
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
            max_public_api_names=1,
        ),
    )

    message = findings[0].message
    assert (
        "Package namespace import candidates (syntax only; not verified exports)"
        in message
    )
    assert (
        "src/gateway/__init__.py:1 imports GatewayClient from "
        "src/gateway/gateway_client.py as package name PublicClient"
    ) in message
    assert "1 package import name(s) omitted by max_public_api_names" in message
    assert "Package-level import candidates are not verified re-exports" in message


def test_python_package_init_resolves_relative_submodule_import_candidate(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    init = _write(tmp_path, "src/gateway/__init__.py")
    paths.append(init)
    (tmp_path / "src/gateway/__init__.py").write_text(
        "from . import gateway_client as client\n", encoding="utf-8"
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    message = findings[0].message
    assert "src/gateway/__init__.py:1 → src/gateway/gateway_client.py" in message
    assert (
        "src/gateway/__init__.py:1 imports gateway_client from "
        "src/gateway/gateway_client.py as package name client"
    ) in message


def test_external_explicit_package_submodule_import_is_reported_as_ambiguous(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/pkg/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    init = _write(tmp_path, "src/pkg/__init__.py")
    (tmp_path / init).write_text("", encoding="utf-8")
    consumer = _write(tmp_path, "src/app.py")
    (tmp_path / consumer).write_text(
        "from pkg import gateway_client\n", encoding="utf-8"
    )

    findings = source_family_findings(
        tmp_path,
        [*paths, init, consumer],
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    message = next(
        item.message for item in findings if "Family gateway_*" in item.message
    )
    assert (
        "Potential selected Python submodule imports have unresolved package attribute state"
        in message
    )
    assert "src/app.py:1 may load src/pkg/gateway_client.py" in message
    assert "No direct external references were observed" not in message


def test_external_namespace_package_submodule_import_is_reported_as_ambiguous(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/pkg/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    consumer = _write(tmp_path, "src/app.py")
    (tmp_path / consumer).write_text(
        "from pkg import gateway_client\n", encoding="utf-8"
    )

    findings = source_family_findings(
        tmp_path,
        [*paths, consumer],
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    message = next(
        item.message for item in findings if "Family gateway_*" in item.message
    )
    assert (
        "Potential selected Python submodule imports have unresolved package attribute state"
        in message
    )
    assert "src/app.py:1 may load src/pkg/gateway_client.py" in message
    assert "No direct external references were observed" not in message


@pytest.mark.parametrize(
    "import_statement",
    (
        "import pkg.gateway_client",
        "from pkg.gateway_client import Client",
        "from pkg import gateway_client",
        "from . import gateway_client",
    ),
)
def test_external_imports_with_duplicate_module_roots_are_ambiguous(
    tmp_path: Path, import_statement: str
) -> None:
    paths = [
        _write(tmp_path, f"src/pkg/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    duplicate = _write(tmp_path, "vendor/pkg/gateway_client.py")
    consumer = _write(tmp_path, "src/pkg/app.py")
    (tmp_path / consumer).write_text(f"{import_statement}\n", encoding="utf-8")

    findings = source_family_findings(
        tmp_path,
        [*paths, duplicate, consumer],
        SourceFamilyPolicy(
            min_family_files=5,
            exclude=(),
            python_import_evidence=True,
            python_module_roots=("src", "vendor"),
        ),
    )

    message = next(
        item.message for item in findings if "Family gateway_*" in item.message
    )
    assert (
        "Potential selected Python imports have ambiguous module-root candidates"
        in message
    )
    assert "src/pkg/app.py:1 may resolve to src/pkg/gateway_client.py" in message
    assert "No direct external references were observed" not in message


@pytest.mark.skipif(
    any(
        find_spec(module) is None
        for module in (
            "tree_sitter",
            "tree_sitter_javascript",
            "tree_sitter_typescript",
        )
    ),
    reason="install the optional alphus[javascript] parser extra",
)
def test_javascript_oversized_reads_consume_the_shared_byte_budget(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.js")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    for path in paths:
        (tmp_path / path).write_text("// " + "x" * 256, encoding="utf-8")

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            javascript_import_evidence=True,
            max_import_analysis_bytes=64,
        ),
    )

    assert any(
        "configured JavaScript/TypeScript import byte budget was exhausted"
        in item.message
        for item in findings
    )


def test_import_evidence_reports_bounded_qualified_protocol_contracts(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    (tmp_path / "src/gateway_client.py").write_text(
        "import typing\n"
        "class Client(typing.Protocol):\n"
        "    def send(self, payload: bytes) -> None: ...\n"
        "class Store(typing.Protocol[object]):\n"
        "    def read(self) -> bytes: ...\n",
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
            max_contract_declarations=1,
        ),
    )

    message = findings[0].message
    assert (
        "src/gateway_client.py:2 declares Client with Protocol base (send)" in message
    )
    assert "1 declaration(s) omitted by max_contract_declarations" in message
    assert (
        "other shared-contract forms, and non-Python dependencies are not assessed"
        in message
    )


def test_import_evidence_does_not_treat_unqualified_protocol_alias_as_resolved(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    (tmp_path / "src/gateway_client.py").write_text(
        "from typing import Protocol as Contract\n"
        "class Client(Contract):\n"
        "    def send(self) -> None: ...\n",
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    message = findings[0].message
    assert "No qualified typing.Protocol or typing_extensions.Protocol" in message
    assert "aliases, ABCs, and other contract forms are not assessed" in message


def test_import_evidence_reports_cross_file_protocol_type_references(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache", "contracts")
    ]
    (tmp_path / "src/gateway_contracts.py").write_text(
        "import typing\n"
        "class Connector(typing.Protocol):\n"
        "    def send(self, payload: bytes) -> None: ...\n",
        encoding="utf-8",
    )
    (tmp_path / "src/gateway_client.py").write_text(
        "from gateway_contracts import Connector as Port\n"
        "def connect(channel: Port) -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    message = findings[0].message
    assert (
        "src/gateway_client.py:2 references Protocol type Port from "
        "src/gateway_contracts.py"
    ) in message
    assert (
        "consumers outside the selected Python inventory, dynamic references" in message
    )


def test_import_evidence_reports_qualified_typed_dict_contract_and_usage(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache", "contracts")
    ]
    (tmp_path / "src/gateway_contracts.py").write_text(
        "import typing\n"
        "class Payload(typing.TypedDict):\n"
        "    request_id: str\n"
        "    accepted: bool\n",
        encoding="utf-8",
    )
    (tmp_path / "src/gateway_client.py").write_text(
        "from gateway_contracts import Payload\n"
        "def send(payload: Payload) -> None: ...\n",
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=6,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    message = findings[0].message
    assert (
        "src/gateway_contracts.py:2 declares Payload with qualified TypedDict base "
        "(request_id, accepted)"
    ) in message
    assert (
        "src/gateway_client.py:2 references TypedDict type Payload from "
        "src/gateway_contracts.py"
    ) in message


def test_import_evidence_does_not_claim_typed_dict_factory_contracts(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache", "contracts")
    ]
    (tmp_path / "src/gateway_contracts.py").write_text(
        "import typing\nPayload = typing.TypedDict('Payload', {'request_id': str})\n",
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=6,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    assert "No qualified typing.TypedDict" in findings[0].message
    assert "factory declarations" in findings[0].message


def test_import_evidence_abstains_when_protocol_import_name_is_rebound(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache", "contracts")
    ]
    (tmp_path / "src/gateway_contracts.py").write_text(
        "import typing\nclass Port(typing.Protocol):\n    def send(self) -> None: ...\n",
        encoding="utf-8",
    )
    (tmp_path / "src/gateway_client.py").write_text(
        "from gateway_contracts import Port\n"
        "Port = object\n"
        "def connect(channel: Port) -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    assert "No direct cross-file type reference to a detected qualified Protocol" in (
        findings[0].message
    )


@pytest.mark.parametrize(
    "declaration",
    (
        "__all__ = make_exports()",
        "__all__ = ['first']\n__all__ += ['second']",
        "__all__ = ['first']\n__all__ = ['second']",
    ),
)
def test_import_evidence_abstains_on_dynamic_or_reassigned_exports(
    tmp_path: Path, declaration: str
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    (tmp_path / "src/gateway_client.py").write_text(
        declaration + "\n", encoding="utf-8"
    )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    message = findings[0].message
    assert "Literal export names could not be resolved" in message
    assert "does not establish that names are private" not in message


def test_python_import_evidence_shows_unresolved_edges_and_truncation(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/{family}_{name}.py")
        for family in ("gateway", "storage")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    (tmp_path / "src/gateway_client.py").write_text(
        "import gateway_server\nimport external_client\n", encoding="utf-8"
    )
    (tmp_path / "src/gateway_server.py").write_text(
        "from gateway_client import connect\nimport external_server\n",
        encoding="utf-8",
    )
    for name in ("routes", "auth", "cache"):
        (tmp_path / f"src/gateway_{name}.py").write_text(
            f"import external_{name}\n", encoding="utf-8"
        )
    for name in ("client", "server", "routes", "auth", "cache"):
        (tmp_path / f"src/storage_{name}.py").write_text(
            f"import external_storage_{name}\n", encoding="utf-8"
        )

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
            max_import_edges=1,
        ),
    )

    gateway = next(item for item in findings if "Family gateway_*" in item.message)
    storage = next(item for item in findings if "Family storage_*" in item.message)
    assert "2 resolved edge(s) target another family member" in gateway.message
    assert "5 import(s) unresolved/outside the configured inventory" in gateway.message
    assert "1 edge(s) omitted by max_import_edges" in gateway.message
    assert "0 resolved edge(s) target another family member" in storage.message
    assert "5 import(s) unresolved/outside the configured inventory" in storage.message


def test_python_import_evidence_reports_selected_external_consumers(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    consumer = tmp_path / "src/app.py"
    consumer.write_text(
        "from gateway_client import Client\nimport gateway_server\n",
        encoding="utf-8",
    )

    findings = source_family_findings(
        tmp_path,
        [*paths, consumer.relative_to(tmp_path)],
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    message = findings[0].message
    assert "2 direct edge(s) target a family member" in message
    assert "parsed 1 of 1 eligible file(s)" in message
    assert "src/app.py:1 → src/gateway_client.py" in message
    assert "src/app.py:2 → src/gateway_server.py" in message
    assert "unselected consumers and dynamic references are not assessed" not in message


@pytest.mark.parametrize(
    ("consumer_path", "import_line"),
    (
        ("src/app.py", "from .gateway_client import Client\n"),
        ("src/pkg/app.py", "from ..gateway_client import Client\n"),
    ),
)
def test_python_external_reference_rejects_relative_import_above_package_root(
    tmp_path: Path, consumer_path: str, import_line: str
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    consumer = tmp_path / consumer_path
    consumer.parent.mkdir(parents=True, exist_ok=True)
    consumer.write_text(import_line, encoding="utf-8")

    findings = source_family_findings(
        tmp_path,
        [*paths, consumer.relative_to(tmp_path)],
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    message = next(
        item.message for item in findings if "Family gateway_*" in item.message
    )
    assert "0 direct edge(s) target a family member" in message
    assert f"{consumer_path}:1 → src/gateway_client.py" not in message


def test_python_import_sources_are_parsed_once_across_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [
        _write(tmp_path, f"src/{family}_{name}.py")
        for family in ("gateway", "storage")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    consumer = tmp_path / "src/app.py"
    consumer.write_text(
        "import gateway_client\nimport storage_client\n", encoding="utf-8"
    )
    paths.append(consumer.relative_to(tmp_path))
    parsed: list[str] = []
    original_parse = source_families.ast.parse

    def count_parse(
        source: str | bytes, filename: str = "<unknown>", mode: str = "exec"
    ) -> ast.Module:
        parsed.append(filename)
        return original_parse(source, filename=filename, mode=mode)

    monkeypatch.setattr(source_families.ast, "parse", count_parse)
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    assert len(parsed) == len(paths)
    assert len(set(parsed)) == len(paths)
    for family in ("gateway", "storage"):
        message = next(
            item.message for item in findings if f"Family {family}_*" in item.message
        )
        assert "1 direct edge(s) target a family member" in message
        assert "parsed ASTs are reused across family reports" in message


def test_python_import_byte_budget_is_shared_and_reports_missing_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [
        _write(tmp_path, f"src/{family}_{name}.py")
        for family in ("gateway", "storage")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    consumer = tmp_path / "src/app.py"
    consumer.write_text("import gateway_client\n", encoding="utf-8")
    paths.append(consumer.relative_to(tmp_path))
    # The first family's core plus the consumer fit, but the rest of the second
    # family did not. The run-wide pass now spends the cap on family cores first.
    budget = sum(
        (tmp_path / path).stat().st_size
        for path in paths
        if path.name.startswith("gateway_") or path.name == "app.py"
    )
    parsed: list[str] = []
    original_parse = source_families.ast.parse

    def count_parse(
        source: str | bytes, filename: str = "<unknown>", mode: str = "exec"
    ) -> ast.Module:
        parsed.append(filename)
        return original_parse(source, filename=filename, mode=mode)

    monkeypatch.setattr(source_families.ast, "parse", count_parse)
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
            max_import_analysis_bytes=budget,
        ),
    )

    assert len(parsed) == 7
    assert "src/app.py" not in parsed
    assert (
        sum(
            (tmp_path / path).stat().st_size
            for path in paths
            if path.as_posix() in parsed
        )
        <= budget
    )
    assert any(
        "Python import byte budget was exhausted across the source-family run"
        in item.message
        for item in findings
    )
    assert any("no clean result can be inferred" in item.message for item in findings)


def test_python_import_budget_reserves_all_family_cores_before_external_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core_paths = [
        _write(tmp_path, f"src/{family}_{name}.py")
        for family in ("gateway", "storage")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    unrelated = tmp_path / "src/aaa_unrelated.py"
    unrelated.write_text("u" * 19 + "\n", encoding="utf-8")
    paths = [*core_paths, unrelated.relative_to(tmp_path)]
    core_budget = sum((tmp_path / path).stat().st_size for path in core_paths)
    parsed: list[str] = []
    original_parse = source_families.ast.parse

    def count_parse(
        source: str | bytes, filename: str = "<unknown>", mode: str = "exec"
    ) -> ast.Module:
        parsed.append(filename)
        return original_parse(source, filename=filename, mode=mode)

    monkeypatch.setattr(source_families.ast, "parse", count_parse)
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
            max_import_analysis_bytes=core_budget,
        ),
    )

    assert set(parsed) == {path.as_posix() for path in core_paths}
    assert unrelated.as_posix() not in parsed
    assert any(
        "Python import byte budget was exhausted across the source-family run"
        in item.message
        for item in findings
    )
    for family in ("gateway", "storage"):
        message = next(
            item.message for item in findings if f"Family {family}_*" in item.message
        )
        assert "could not be analyzed" in message


def test_python_external_consumer_scan_reports_budget_exhaustion(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    consumer = tmp_path / "src/app.py"
    consumer.write_text("import gateway_client\n", encoding="utf-8")
    family_bytes = sum((tmp_path / path).stat().st_size for path in paths)

    findings = source_family_findings(
        tmp_path,
        [*paths, consumer.relative_to(tmp_path)],
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
            max_import_analysis_bytes=family_bytes,
        ),
    )

    assert "could not be analyzed" in findings[0].message
    message = next(
        item.message for item in findings if "Family gateway_*" in item.message
    )
    assert "External reference scan incomplete" in message
    assert "missing references are unknown" in message
    assert "No direct external references were observed" not in message


def test_import_evidence_requires_explicit_module_root() -> None:
    with pytest.raises(ValueError, match="requires explicit python_module_roots"):
        SourceFamilyPolicy(python_import_evidence=True)


def test_import_parse_failure_is_reported_as_incomplete(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    (tmp_path / "src/gateway_client.py").write_text("def broken(:\n", encoding="utf-8")

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    assert any("could not be analyzed" in finding.message for finding in findings)
    assert any(
        "no clean result can be inferred" in finding.message for finding in findings
    )


def test_external_python_recursion_error_is_reported_as_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    consumer = _write(tmp_path, "src/app.py")
    terms = " + ".join("1" for _ in range(4000))
    (tmp_path / consumer).write_text(f"value = {terms}\n", encoding="utf-8")
    original_parse = ast.parse

    def parse_with_recursion_failure(
        source: str | bytes,
        filename: str = "<unknown>",
        mode: str = "exec",
        **kwargs: object,
    ) -> ast.Module:
        if filename == consumer.as_posix():
            raise RecursionError("simulated AST recursion limit")
        return original_parse(source, filename=filename, mode=mode, **kwargs)

    monkeypatch.setattr(source_families.ast, "parse", parse_with_recursion_failure)
    findings = source_family_findings(
        tmp_path,
        [*paths, consumer],
        SourceFamilyPolicy(
            min_family_files=5,
            python_import_evidence=True,
            python_module_roots=("src",),
        ),
    )

    message = next(
        item.message for item in findings if "Family gateway_*" in item.message
    )
    assert "External reference scan incomplete: 1" in message
    assert "missing references are unknown" in message
    assert "No direct external references were observed" not in message


def test_scope_exclusions_extensions_and_language_override_precedence(
    tmp_path: Path,
) -> None:
    names = ("client", "server", "routes", "auth", "cache")
    included = [_write(tmp_path, f"app/gateway_{name}.h") for name in names]
    path_overridden = [_write(tmp_path, f"app/c/gateway_{name}.h") for name in names]
    excluded = [
        _write(tmp_path, f"app/{directory}/gateway_{name}.h")
        for directory in (
            "tests",
            "generated",
            "fixtures",
            "compat",
            "vendor",
            "schema",
        )
        for name in names
    ]
    policy = SourceFamilyPolicy(
        include=("app/**",),
        exclude=(
            "app/tests/**",
            "app/generated/**",
            "app/fixtures/**",
            "app/compat/**",
            "app/vendor/**",
            "app/schema/**",
        ),
        extensions=(".h",),
        language_overrides=((".h", "C"),),
        path_language_overrides=(("app/**", "C++"), ("app/c/**", "C")),
        min_family_files=5,
    )
    paths = [*included, *path_overridden, *excluded]

    findings = source_family_findings(tmp_path, paths, policy)
    assert len(findings) == 2
    assert "language mix C++=5" in findings[0].message
    assert "language mix C=5" in findings[1].message
    assert all("5 of 5 selected sibling" in finding.message for finding in findings)
    assert all("last match wins" in finding.message for finding in findings)
    assert all("app/generated/gateway_" not in finding.message for finding in findings)
    assert all("app/compat/gateway_" not in finding.message for finding in findings)


@pytest.mark.parametrize(
    ("extension", "expected_language"),
    [
        (".py", "Python"),
        (".c", "C"),
        (".cpp", "C++"),
        (".js", "JavaScript"),
        (".ts", "TypeScript"),
    ],
)
def test_supports_python_c_cpp_and_javascript_families(
    tmp_path: Path, extension: str, expected_language: str
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}{extension}")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(extensions=(extension,), min_family_files=5),
    )
    assert len(findings) == 1
    assert f"language mix {expected_language}=5" in findings[0].message


@pytest.mark.parametrize(
    ("header_extension", "implementation_extension", "language_mix"),
    [(".h", ".c", "C=5, C/C++=5"), (".hpp", ".cpp", "C++=10")],
)
def test_pairs_c_cpp_headers_and_sources_but_keeps_physical_file_counts(
    tmp_path: Path,
    header_extension: str,
    implementation_extension: str,
    language_mix: str,
) -> None:
    paths = []
    for name in ("cache", "client", "config", "cursor", "codec"):
        paths.append(_write(tmp_path, f"src/gateway_{name}{header_extension}"))
        paths.append(_write(tmp_path, f"src/gateway_{name}{implementation_extension}"))

    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(
            extensions=(header_extension, implementation_extension),
            min_family_files=5,
            file_length_limits=(
                (header_extension, 300),
                (implementation_extension, 500),
            ),
        ),
    )

    assert len(findings) == 1
    assert "5 logical units across 10 physical files" in findings[0].message
    assert "10 of 10 selected sibling source files" in findings[0].message
    assert f"language mix {language_mix}" in findings[0].message
    assert f"{implementation_extension}≤500 lines" in findings[0].message
    assert f"{header_extension}≤300 lines" in findings[0].message


def test_does_not_pair_same_stem_files_across_unrelated_languages(
    tmp_path: Path,
) -> None:
    paths = []
    for name in ("client", "server", "routes", "auth", "cache"):
        paths.append(_write(tmp_path, f"src/gateway_{name}.py"))
        paths.append(_write(tmp_path, f"src/gateway_{name}.ts"))
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(extensions=(".py", ".ts"), min_family_files=5),
    )
    assert len(findings) == 1
    assert "10 logical units across 10 physical files" in findings[0].message
    assert "language mix Python=5, TypeScript=5" in findings[0].message


def test_case_sensitive_stems_do_not_create_false_header_source_pairs(
    tmp_path: Path,
) -> None:
    paths = []
    for name in ("cache", "client", "config", "cursor", "codec"):
        paths.append(_write(tmp_path, f"src/gateway_{name}.h"))
        paths.append(_write(tmp_path, f"src/gateway_{name}.c"))
    paths.extend(
        [
            _write(tmp_path, "src/gateway_Legacy.h"),
            _write(tmp_path, "src/gateway_legacy.c"),
        ]
    )
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(extensions=(".h", ".c"), min_family_files=5),
    )
    assert len(findings) == 1
    assert "7 logical units across 12 physical files" in findings[0].message


def test_nested_prefixes_are_partitioned_without_duplicate_members(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_admin_{name}.py")
        for name in ("create", "delete", "load", "save", "update")
    ] + [
        _write(tmp_path, f"src/gateway_client_{name}.py")
        for name in ("create", "delete", "load", "save", "update")
    ]
    findings = source_family_findings(
        tmp_path, paths, SourceFamilyPolicy(min_family_files=5)
    )
    assert len(findings) == 2
    assert "Family gateway_admin_*" in findings[0].message
    assert "Family gateway_client_*" in findings[1].message
    assert all("gateway_*" not in finding.message for finding in findings)


def test_tokenization_and_directory_boundaries_are_explicit(tmp_path: Path) -> None:
    root_family = [
        _write(tmp_path, f"src/{name}.py")
        for name in (
            "GatewayClient",
            "gateway_server",
            "gateway-routes",
            "gateway.auth",
            "gatewayCache",
        )
    ]
    nested_family = [
        _write(tmp_path, f"src/impl/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    findings = source_family_findings(
        tmp_path,
        [*root_family, *nested_family],
        SourceFamilyPolicy(min_family_files=5),
    )
    assert [
        (finding.path, "Family gateway_*" in finding.message) for finding in findings
    ] == [
        ("src", True),
        ("src/impl", True),
    ]


def test_prefix_minimum_and_family_threshold_are_configurable(tmp_path: Path) -> None:
    short_prefix = [
        _write(tmp_path, f"src/api_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    too_few = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth")
    ]
    assert (
        source_family_findings(
            tmp_path,
            short_prefix,
            SourceFamilyPolicy(min_family_files=5, min_prefix_characters=4),
        )
        == []
    )
    assert (
        len(
            source_family_findings(
                tmp_path,
                short_prefix,
                SourceFamilyPolicy(min_family_files=5, min_prefix_characters=3),
            )
        )
        == 1
    )
    assert (
        source_family_findings(
            tmp_path,
            too_few,
            SourceFamilyPolicy(min_family_files=5, min_prefix_characters=4),
        )
        == []
    )

    findings = source_family_findings(
        tmp_path,
        too_few,
        SourceFamilyPolicy(min_family_files=4, min_prefix_characters=4),
    )
    assert len(findings) == 1


def test_empty_inventory_has_no_findings(tmp_path: Path) -> None:
    assert source_family_findings(tmp_path, [], SourceFamilyPolicy()) == []


def test_line_count_handles_newline_variants_and_chunk_boundaries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "newlines.py"
    path.write_bytes(("a" * 65_535 + "\r\nb\rc\n" + "d\u2028e").encode("utf-8"))
    assert source_families._line_count(path) == 5


def test_input_order_does_not_change_grouping_or_serialized_findings(
    tmp_path: Path,
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py", lines)
        for name, lines in (
            ("client", 3),
            ("server", 7),
            ("routes", 4),
            ("auth", 5),
            ("cache", 6),
        )
    ]
    policy = SourceFamilyPolicy(min_family_files=5)
    forward = source_family_findings(tmp_path, paths, policy)
    reverse = source_family_findings(tmp_path, reversed(paths), policy)
    assert forward == reverse


def test_large_inventory_is_bounded_and_partial_results_are_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("auth", "cache", "client", "routes", "server")
    ]
    paths.extend(Path(f"src/zfamily_{index}_client.py") for index in range(10_000))
    reads: list[Path] = []
    line_count = source_families._line_count

    def track_read(path: Path) -> int:
        reads.append(path)
        return line_count(path)

    monkeypatch.setattr(source_families, "_line_count", track_read)
    limited = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(min_family_files=2, max_files=2),
    )
    assert len(limited) == 2
    assert len(reads) == 2
    assert any("scan incomplete" in finding.message for finding in limited)
    assert any(
        "no clean result can be inferred" in finding.message for finding in limited
    )


def test_member_evidence_is_bounded_and_explicitly_truncated(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_member_{index}.py", index + 1)
        for index in range(5)
    ]
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(min_family_files=5, max_reported_members=2),
    )
    assert len(findings) == 1
    assert "Members (showing 2 of 5)" in findings[0].message
    assert "member evidence truncated" in findings[0].message


def test_output_limit_is_explicit(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, f"src/{group}_{member}.py")
        for group in ("alpha", "bravo", "charlie")
        for member in ("one", "two", "three", "four", "five")
    ]
    findings = source_family_findings(
        tmp_path,
        paths,
        SourceFamilyPolicy(min_family_files=5, max_findings=1),
    )
    assert len(findings) == 1
    assert "output truncated" in findings[0].message

    partial_paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    partial_paths.append(_write(tmp_path, "src/independent.py"))
    partial = source_family_findings(
        tmp_path,
        partial_paths,
        SourceFamilyPolicy(min_family_files=5, max_files=5, max_findings=1),
    )
    assert len(partial) == 1
    assert "output truncated" in partial[0].message
    assert "scan was also incomplete" in partial[0].message


def test_unreadable_source_remains_in_lexical_candidate_and_marks_scan_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [
        _write(tmp_path, f"src/gateway_{name}.py")
        for name in ("client", "server", "routes", "auth", "cache")
    ]
    unreadable = paths[-1]

    def fail_read(path: Path) -> int:
        if path.name == unreadable.name:
            raise OSError("synthetic read failure")
        return 2

    monkeypatch.setattr(source_families, "_line_count", fail_read)
    findings = source_family_findings(tmp_path, paths, SourceFamilyPolicy())
    assert len(findings) == 2
    assert any("scan incomplete" in finding.message for finding in findings)
    candidate = next(
        finding for finding in findings if "Family gateway_*" in finding.message
    )
    assert "5 logical units across 5 physical files" in candidate.message
    assert "1 unavailable" in candidate.message
    assert "line count unavailable" in candidate.message


@pytest.mark.parametrize(
    "invalid_policy",
    [
        pytest.param(lambda: SourceFamilyPolicy(min_family_files=0), id="min-family"),
        pytest.param(lambda: SourceFamilyPolicy(max_files=0), id="max-files"),
        pytest.param(
            lambda: SourceFamilyPolicy(max_contract_declarations=0),
            id="max-contract-declarations",
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(max_reported_members=0), id="max-members"
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(extensions=(".py", ".py")), id="extensions"
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(exclude=("../private/**",)), id="exclude"
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(file_length_limits=((".py", 0),)),
            id="file-length",
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(
                language_overrides=((".py", "Python"), (".py", "Py"))
            ),
            id="duplicate-language-override",
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(language_overrides=(("invalid", "Py"),)),
            id="invalid-language-override",
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(
                path_language_overrides=(("../outside/**", "C"),)
            ),
            id="invalid-path-language-override",
        ),
        pytest.param(
            lambda: SourceFamilyPolicy(max_scope_patterns=1), id="scope-bound"
        ),
    ],
)
def test_rejects_invalid_source_family_policy(
    invalid_policy: Callable[[], SourceFamilyPolicy],
) -> None:
    with pytest.raises(ValueError):
        invalid_policy()
