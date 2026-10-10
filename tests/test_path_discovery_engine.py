"""Path-discovery gate coverage for Python and JavaScript sources."""

from pathlib import Path

from alphus.config import PathDiscoveryPolicy
from alphus.path_discovery import (
    check_path_discovery,
    js_inspection_findings,
    js_path_findings,
    python_inspection_findings,
    python_path_findings,
)


def test_selected_parent_walk_is_flagged(tmp_path: Path) -> None:
    """The reported DTED0 pattern must be visible in the checkout inventory."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    relative = Path("scripts/verify.py")
    (tmp_path / relative).write_text(
        "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n",
        encoding="utf-8",
    )
    findings = check_path_discovery(
        tmp_path,
        [relative],
        PathDiscoveryPolicy(extensions=[".py"], exclude=[], inspection_exclude=[]),
    )
    assert [(item.path, item.line, item.message) for item in findings] == [
        ("scripts/verify.py", 2, "module __file__ used to infer a parent root")
    ]


def test_cwd_and_parent_chain_are_flagged() -> None:
    """Changing the syntax does not hide implicit path roots."""
    source = (
        "from pathlib import Path\nimport os\n"
        "root = Path(__file__).resolve().parent.parent\n"
        "working = Path.cwd()\n"
        "other = os.getcwd()\n"
    )
    assert python_path_findings(source) == [
        (3, "module __file__ used to infer a parent root"),
        (4, "Path.cwd() used as an implicit path root"),
        (5, "os.getcwd() used as an implicit path root"),
    ]


def test_sys_path_mutations_are_flagged_through_import_and_assignment_aliases() -> None:
    source = (
        "import sys as runtime\n"
        "runtime.path.insert(0, local_package)\n"
        "from sys import path as module_path\n"
        "module_path.extend(plugin_paths)\n"
        "search_path = module_path\n"
        "search_path[0:0] = checkout_paths\n"
        "search_path += optional_paths\n"
    )
    assert python_path_findings(source) == [
        (2, "sys.path mutated for local module discovery"),
        (4, "sys.path mutated for local module discovery"),
        (6, "sys.path mutated for local module discovery"),
        (7, "sys.path mutated for local module discovery"),
    ]


def test_sys_path_assignment_augmented_assignment_and_delete_are_flagged() -> None:
    source = (
        "import sys\n"
        "sys.path = [checkout]\n"
        "sys.path += plugins\n"
        "sys.path[0] = replacement\n"
        "del sys.path[1]\n"
    )
    assert python_path_findings(source) == [
        (2, "sys.path mutated for local module discovery"),
        (3, "sys.path mutated for local module discovery"),
        (4, "sys.path mutated for local module discovery"),
        (5, "sys.path mutated for local module discovery"),
    ]


def test_reading_or_copying_sys_path_is_not_mutation() -> None:
    source = "import sys\nsnapshot = tuple(sys.path)\nsnapshot.append(local_module)\n"
    assert python_path_findings(source) == []


def test_js_module_url_and_cwd_are_flagged() -> None:
    """The same policy reaches authored Node scripts."""
    source = (
        "const here = dirname(fileURLToPath(import.meta.url));\n"
        "const root = process.cwd();\n"
        "const fallback = path.resolve();\n"
    )
    assert js_path_findings(source) == [
        (1, "module URL used as an implicit path root"),
        (2, "current working directory used as an implicit path root"),
        (3, "current working directory used as an implicit path root"),
    ]


def test_nested_call_reports_the_path_line_once() -> None:
    """An argparse wrapper does not duplicate the nested path finding."""
    source = (
        "from pathlib import Path\n"
        "parser.add_argument(\n"
        "    '--output', default=Path(__file__).resolve().parents[1]\n"
        ")\n"
    )
    assert python_path_findings(source) == [
        (3, "module __file__ used to infer a parent root")
    ]


def test_interpreter_location_is_not_a_checkout_contract() -> None:
    """An executable's install location is another implicit root heuristic."""
    assert python_path_findings("root = Path(sys.executable).resolve().parent\n") == [
        (1, "sys.executable used to derive a path")
    ]


def test_git_root_command_is_flagged_without_flagging_a_policy_string() -> None:
    """Only executed Git root discovery is a path finding."""
    source = (
        "import subprocess\n"
        "text = '--show-toplevel'\n"
        "root = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'])\n"
    )
    assert python_path_findings(source) == [
        (3, "Git checkout discovery used as an implicit path root")
    ]


def test_explicit_root_parameter_is_clean() -> None:
    """A caller-provided path is not checkout discovery."""
    source = "from pathlib import Path\ndef build(root: Path) -> Path:\n    return root / 'out'\n"
    assert python_path_findings(source) == []


def test_colocated_resource_and_esm_main_guard_are_clean() -> None:
    """A local asset path and direct-entry check do not infer a parent root."""
    assert python_path_findings("asset = Path(__file__).parent / 'data.json'\n") == []
    assert (
        js_path_findings(
            "if (fileURLToPath(import.meta.url) === process.argv[1]) main();\n"
        )
        == []
    )


def test_slash_and_url_heuristics_are_reported() -> None:
    """The selected offline-map guard is an actionable inspection finding."""
    source = (
        'if raw.startswith(("\\\\\\\\", "//")) or "://" in raw:\n'
        '    raise ValueError("network path")\n'
    )
    assert python_inspection_findings(source) == [
        (1, "URL scheme substring test; parse with urlsplit"),
        (1, "slash prefix test; parse the declared path flavor"),
    ]


def test_separator_rewrite_is_reported_but_text_formatting_is_not() -> None:
    """String path normalization is distinct from ordinary text cleanup."""
    assert python_inspection_findings('name = raw.replace("\\\\", "/")\n') == [
        (1, "separator rewrite; parse the declared path flavor")
    ]
    assert python_inspection_findings('text = text.replace("\\n", " ")\n') == []


def test_structured_path_and_url_inspection_passes() -> None:
    """Pure paths and parsed URLs avoid separator guessing."""
    source = (
        "windows = PureWindowsPath(raw)\n"
        "posix = PurePosixPath(raw)\n"
        "scheme = urlsplit(raw).scheme\n"
    )
    assert python_inspection_findings(source) == []


def test_javascript_slash_checks_are_reported() -> None:
    """The rule also reaches authored browser and Node code."""
    source = (
        'if (path.startsWith("/")) reject();\n'
        'if (raw.includes("://")) reject();\n'
        'const normalized = name.replaceAll("\\\\", "/");\n'
        'if (source.startsWith("https://")) accept();\n'
    )
    assert js_inspection_findings(source) == [
        (1, "slash prefix test; parse the declared path flavor"),
        (2, "URL scheme substring test; parse with URL"),
        (3, "separator rewrite; parse the declared path flavor"),
        (4, "URL prefix test; parse with URL"),
    ]


def test_test_assertions_are_outside_path_inspection_gate(tmp_path: Path) -> None:
    """Test paths skip inspection patterns but retain implicit-root checks."""
    tests = tmp_path / "tests"
    tests.mkdir()
    relative = Path("tests/test_paths.py")
    (tmp_path / relative).write_text(
        'root = Path(__file__).resolve().parents[1]\nassert raw.startswith("/")\n',
        encoding="utf-8",
    )
    findings = check_path_discovery(
        tmp_path,
        [relative],
        PathDiscoveryPolicy(
            extensions=[".py"],
            exclude=[],
            inspection_exclude=["**/tests/**", "tests/**", "**/test_*", "test_*"],
        ),
    )

    assert [(item.path, item.line, item.message) for item in findings] == [
        ("tests/test_paths.py", 1, "module __file__ used to infer a parent root")
    ]
