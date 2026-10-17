"""Output escaping scanners are covered without a repository-specific layout."""

from pathlib import Path

from alphus.config import SourceScanPolicy
from alphus.output_escaping import (
    check_output_escaping,
    js_escape_findings,
    python_escape_findings,
)


def test_python_detects_common_format_escapes() -> None:
    """Replacement calls and escape tables are reported by source location."""
    source = (
        'value = value.replace("|", "\\\\|")\n'
        'value = value.replace("<", "&lt;")\n'
        'table = {"&": r"\\&", "#": r"\\#"}\n'
        'value = value.replace("\\n", "\\\\n")\n'
    )
    assert [line for line, _ in python_escape_findings(source)] == [1, 2, 3, 4]


def test_python_allows_serializers_and_plain_normalization() -> None:
    """Serialization and ordinary text normalization remain accepted."""
    source = (
        "value = html.escape(value)\n"
        "value = json.dumps(record)\n"
        'value = value.replace("\\n", " ")\n'
    )
    assert python_escape_findings(source) == []


def test_javascript_detects_escape_chains() -> None:
    """HTML entity and Markdown escape replacement chains are detected."""
    source = (
        'const html = value.replaceAll("&", "&amp;");\n'
        'const md = value.replaceAll("|", "\\\\|");\n'
    )
    assert [line for line, _ in js_escape_findings(source)] == [1, 2]


def test_javascript_allows_json_and_plain_normalization() -> None:
    """JSON serialization and non-escaping replacements stay clean."""
    source = (
        "const output = JSON.stringify(value);\n"
        'const name = value.replaceAll(" ", "-");\n'
        'const portable = value.replaceAll("\\\\", "/");\n'
    )
    assert js_escape_findings(source) == []


def test_scan_uses_extensions_and_exclusions_from_policy(tmp_path: Path) -> None:
    """The portable checker honors caller scope without layout assumptions."""
    sources = {
        Path("src/render.py"): 'value = value.replace("<", "&lt;")\n',
        Path("vendor/codec.py"): 'value = value.replace("<", "&lt;")\n',
        Path("tests/test_render.py"): 'value = value.replace("<", "&lt;")\n',
        Path("docs/example.md"): 'value = value.replace("<", "&lt;")\n',
    }
    for relative, source in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    policy = SourceScanPolicy(
        extensions=[".py"],
        exclude=["**/vendor/**", "vendor/**"],
    )

    findings = check_output_escaping(tmp_path, list(sources), policy)

    assert [(finding.path, finding.line, finding.message) for finding in findings] == [
        (
            "src/render.py",
            1,
            "manual output escape replacement; use a library or tested shared utility",
        ),
        (
            "tests/test_render.py",
            1,
            "manual output escape replacement; use a library or tested shared utility",
        ),
    ]
