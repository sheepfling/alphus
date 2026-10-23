"""Portable architecture, layout, version, and callable registry policy checks."""

import json
from pathlib import Path

import pytest

from alphus.config import (
    ArchitectureGraphPolicy,
    CallableRegistryPolicy,
    PackageBoundaryPolicy,
    RepositoryLayoutPolicy,
    VersionSyncPolicy,
)
from alphus.gates.repository.architecture_graph import check_architecture_graph
from alphus.gates.repository.callable_registry import check_callable_registry
from alphus.gates.repository.repository_layout import check_repository_layout
from alphus.gates.repository.version_sync import check_version_sync


def test_architecture_graph_matches_configured_package_edges(tmp_path: Path) -> None:
    policy = PackageBoundaryPolicy.model_validate(
        {
            "metadata_patterns": ["packages/*/pyproject.toml"],
            "source_directory": "src",
            "allowed_dependencies": {"framework": [], "plugin": ["framework"]},
        }
    )
    graph = ArchitectureGraphPolicy.model_validate(
        {
            "path": "docs/architecture.md",
            "node_names": {"framework": "Core", "plugin": "Plugin"},
            "extra_edges": [["Client", "Service"]],
        }
    )
    guide = tmp_path / graph.path
    guide.parent.mkdir()
    guide.write_text(
        "```mermaid\nflowchart TB\nPlugin -->|uses| Core\n"
        "Client -->|http| Service\n```\n",
        encoding="utf-8",
    )

    assert check_architecture_graph(tmp_path, graph, policy) == []
    guide.write_text(
        "```mermaid\nflowchart TB\nCore -->|uses| Plugin\n```\n", encoding="utf-8"
    )

    assert [
        finding.message for finding in check_architecture_graph(tmp_path, graph, policy)
    ] == [
        "Mermaid graph lacks Client -> Service",
        "Mermaid graph lacks Plugin -> Core",
        "Mermaid graph has forbidden Core -> Plugin",
    ]


@pytest.mark.parametrize(
    ("syntax", "diagram"),
    [
        ("flowchart", "flowchart LR\nPlugin-->Core\nClient-->|http|Service\n"),
        (
            "architecture",
            "architecture-beta\nservice Plugin(server)[Plugin]\n"
            "service Core(server)[Core]\nservice Client(server)[Client]\n"
            "service Service(server)[Service]\nPlugin:R --> L:Core\n"
            "Client:R --> L:Service\n",
        ),
    ],
)
def test_architecture_graph_uses_configured_mermaid_syntax(
    tmp_path: Path, syntax: str, diagram: str
) -> None:
    policy = PackageBoundaryPolicy.model_validate(
        {
            "metadata_patterns": ["packages/*/pyproject.toml"],
            "source_directory": "src",
            "allowed_dependencies": {"framework": [], "plugin": ["framework"]},
        }
    )
    graph = ArchitectureGraphPolicy.model_validate(
        {
            "path": "docs/architecture.md",
            "syntax": syntax,
            "node_names": {"framework": "Core", "plugin": "Plugin"},
            "extra_edges": [["Client", "Service"]],
        }
    )
    guide = tmp_path / graph.path
    guide.parent.mkdir()
    guide.write_text(f"```mermaid\n{diagram}```\n", encoding="utf-8")

    assert check_architecture_graph(tmp_path, graph, policy) == []
    wrong_header = "flowchart LR" if syntax == "architecture" else "architecture-beta"
    guide.write_text(f"```mermaid\n{wrong_header}\n```\n", encoding="utf-8")
    assert [
        finding.rule_id for finding in check_architecture_graph(tmp_path, graph, policy)
    ] == ["architecture.syntax-mismatch"]


def test_repository_layout_checks_paths_manifests_and_python_symbols(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "project.json"
    manifest.write_text(json.dumps({"workspaces": []}), encoding="utf-8")
    policy = RepositoryLayoutPolicy.model_validate(
        {
            "required_paths": [
                {"path": "src/service.py", "message": "service module is missing"}
            ],
            "forbidden_paths": [
                {"path": "legacy", "message": "legacy directory remains"}
            ],
            "forbidden_globs": [
                {"pattern": "old/*.py", "message": "{count} old modules remain"}
            ],
            "required_json_array_values": [
                {
                    "path": "project.json",
                    "key": "workspaces",
                    "value": "apps/client",
                    "message": "client workspace is not registered",
                }
            ],
            "required_python_symbols": [
                {
                    "path": "src/service.py",
                    "symbol": "create_app",
                    "kind": "function",
                    "message": "create_app is missing",
                }
            ],
        }
    )
    (tmp_path / "legacy").mkdir()
    old = tmp_path / "old"
    old.mkdir()
    (old / "compat.py").write_text("", encoding="utf-8")

    findings = check_repository_layout(tmp_path, policy)

    assert [finding.message for finding in findings] == [
        "service module is missing",
        "legacy directory remains",
        "1 old modules remain",
        "client workspace is not registered",
        "create_app is missing",
    ]


def test_repository_layout_checks_tracked_files_and_instruction_routers(
    tmp_path: Path,
) -> None:
    policy = RepositoryLayoutPolicy.model_validate(
        {
            "tracked_suffix_rules": [
                {"suffixes": [".docx", ".xlsx"], "label": "Office"}
            ],
            "tracked_path_rules": [
                {
                    "pattern": "build/reports/*.pdf",
                    "message": "tracked generated report: {path}",
                }
            ],
            "allowed_root_documents": ["README.md", "AGENTS.md", "CLAUDE.md"],
            "instruction_router": {
                "root_instruction_path": "AGENTS.md",
                "root_bridge_path": "CLAUDE.md",
                "root_bridge_marker": "@AGENTS.md",
                "routes": [
                    {
                        "area": "services",
                        "router_path": "services/AGENTS.md",
                        "bridge_path": ".assistant/rules/service-guide.md",
                        "scope_marker": '  - "services/**/*"',
                        "import_marker": "@../../services/AGENTS.md",
                    },
                    {
                        "area": "plugins",
                        "router_path": "plugins/AGENTS.md",
                        "bridge_path": ".assistant/rules/plugins.md",
                        "scope_marker": '  - "plugins/**/*"',
                        "import_marker": "@../../plugins/AGENTS.md",
                    },
                ],
                "required_router_paths": ["services/web/AGENTS.md"],
            },
        }
    )
    (tmp_path / "AGENTS.md").write_text("Root instructions\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    for area in ("services", "plugins", "services/web"):
        router = tmp_path / area / "AGENTS.md"
        router.parent.mkdir(parents=True)
        router.write_text(f"{area} instructions\n", encoding="utf-8")
    for name, area in (("service-guide", "services"), ("plugins", "plugins")):
        bridge = tmp_path / ".assistant/rules" / f"{name}.md"
        bridge.parent.mkdir(parents=True, exist_ok=True)
        bridge.write_text(
            f'  - "{area}/**/*"\n@../../{area}/AGENTS.md\n', encoding="utf-8"
        )
    tracked = [
        Path("budget.docx"),
        Path("build/reports/preview.pdf"),
        Path("NOTES.md"),
    ]

    findings = check_repository_layout(tmp_path, policy, tracked)

    assert [finding.message for finding in findings] == [
        "tracked Office file: budget.docx",
        "tracked generated report: build/reports/preview.pdf",
        "root document is not allowlisted: NOTES.md",
    ]


def test_version_sync_compares_configured_json_and_toml_sources(
    tmp_path: Path,
) -> None:
    (tmp_path / "project.json").write_text('{"version": "2.4.0"}', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "2.3.0"\n', encoding="utf-8"
    )
    policy = VersionSyncPolicy.model_validate(
        {
            "sources": [
                {"path": "project.json", "format": "json", "key": "version"},
                {"path": "pyproject.toml", "format": "toml", "key": "project.version"},
            ]
        }
    )

    findings = check_version_sync(tmp_path, policy)

    assert [(finding.path, finding.message) for finding in findings] == [
        ("pyproject.toml", "version 2.3.0 differs from project.json version 2.4.0")
    ]


def test_callable_registry_matches_public_functions_and_protocol(
    tmp_path: Path,
) -> None:
    (tmp_path / "actions.py").write_text(
        "def start(params):\n    return params\n\n"
        "def stop(params):\n    return params\n",
        encoding="utf-8",
    )
    registry_path = tmp_path / "registry.py"
    registry_path.write_text(
        "from typing import Protocol\n"
        "class Action(Protocol):\n"
        "    def __call__(self, params: object) -> object: ...\n"
        "REGISTRY: dict[str, Action] = {'start': start}\n",
        encoding="utf-8",
    )
    policy = CallableRegistryPolicy.model_validate(
        {
            "source_path": "actions.py",
            "registry_path": "registry.py",
            "protocol_name": "Action",
            "registry_name": "REGISTRY",
        }
    )

    findings = check_callable_registry(tmp_path, policy)

    assert [finding.message for finding in findings] == [
        "public callable stop is not registered"
    ]
    registry_path.write_text(
        "from typing import Protocol\n"
        "class Action(Protocol):\n"
        "    def __call__(self, params: object) -> object: ...\n"
        "REGISTRY: dict[str, Action] = {'start': start, 'stop': stop}\n",
        encoding="utf-8",
    )

    assert check_callable_registry(tmp_path, policy) == []


def test_callable_registry_requires_a_typed_registry_for_public_functions(
    tmp_path: Path,
) -> None:
    (tmp_path / "actions.py").write_text(
        "def start(params):\n    return params\n", encoding="utf-8"
    )
    policy = CallableRegistryPolicy.model_validate(
        {
            "source_path": "actions.py",
            "registry_path": "registry.py",
            "protocol_name": "Action",
            "registry_name": "REGISTRY",
        }
    )

    findings = check_callable_registry(tmp_path, policy)

    assert [finding.message for finding in findings] == [
        "define a typed Action protocol and REGISTRY registry"
    ]


def test_callable_registry_reports_untyped_protocol_and_duplicate_entries(
    tmp_path: Path,
) -> None:
    (tmp_path / "actions.py").write_text(
        "def start(params):\n    return params\n\n"
        "def stop(params):\n    return params\n",
        encoding="utf-8",
    )
    (tmp_path / "registry.py").write_text(
        "from typing import Protocol\n"
        "class Action(Protocol):\n"
        "    def __call__(self, params) -> object: ...\n"
        "REGISTRY: dict[str, Action] = {"
        "'start': start, 'start': start, 'unknown': unknown}\n",
        encoding="utf-8",
    )
    policy = CallableRegistryPolicy.model_validate(
        {
            "source_path": "actions.py",
            "registry_path": "registry.py",
            "protocol_name": "Action",
            "registry_name": "REGISTRY",
        }
    )

    findings = check_callable_registry(tmp_path, policy)

    assert [finding.message for finding in findings] == [
        "Action must define a typed callable Protocol",
        "public callable stop is not registered",
        "registry references unknown callable unknown",
        "public callable start is registered 2 times",
    ]
