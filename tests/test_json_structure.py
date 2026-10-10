"""JSON structure rules stay independent of any one repository layout."""

from pathlib import Path

from alphus.config import SourceScanPolicy
from alphus.json_structure import (
    check_json_structure,
    js_json_findings,
    python_json_findings,
)


def test_python_import_aliases_and_from_imports_are_reported() -> None:
    """Changing import spelling does not evade the Python decoder check."""
    source = (
        "import json as codec\n"
        "from json import load as decode\n"
        "first = codec.loads(text)\n"
        "second = decode(stream)\n"
    )
    assert python_json_findings(source) == [
        (3, "raw JSON decode; validate into a named model"),
        (4, "raw JSON decode; validate into a named model"),
    ]


def test_model_validate_json_is_clean() -> None:
    """Direct model validation is the preferred Python boundary."""
    assert (
        python_json_findings(
            "record = PreparedRecord.model_validate_json(prepared_record.read_bytes())\n"
        )
        == []
    )


def test_javascript_decoders_are_reported() -> None:
    """Browser and Node decoders also create unvalidated values."""
    source = (
        "const record = JSON.parse(text);\n"
        "const payload = await response.json();\n"
        "const nested = await (await sessionResponse).json();\n"
    )
    assert js_json_findings(source) == [
        (1, "JSON.parse returns an unvalidated value"),
        (2, "response.json() returns an unvalidated value"),
        (3, "response.json() returns an unvalidated value"),
    ]


def test_json_serialization_is_clean() -> None:
    """Writing JSON is separate from accepting an unvalidated structure."""
    assert js_json_findings("const text = JSON.stringify(record);\n") == []


def test_scan_uses_configured_extensions_and_exclusions(tmp_path: Path) -> None:
    """A portable rule reads only the paths selected by caller policy."""
    files = {
        Path("src/service.py"): "import json\nvalue = json.loads(text)\n",
        Path("src/client.mjs"): "const value = JSON.parse(text);\n",
        Path("tests/test_service.py"): "import json\nvalue = json.loads(text)\n",
        Path("src/test_fixture.py"): "import json\nvalue = json.loads(text)\n",
        Path(
            "plugins/acme/vendor/decoder.py"
        ): "import json\nvalue = json.loads(text)\n",
        Path("docs/example.md"): "import json\nvalue = json.loads(text)\n",
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    policy = SourceScanPolicy(
        extensions=[".py", ".mjs"],
        exclude=[
            "**/vendor/**",
            "vendor/**",
            "**/tests/**",
            "tests/**",
            "**/test_*",
            "test_*",
        ],
    )

    findings = check_json_structure(tmp_path, list(files), policy)

    assert [(finding.path, finding.line) for finding in findings] == [
        ("src/client.mjs", 1),
        ("src/service.py", 2),
    ]


def test_check_reads_utf8_bom_source(tmp_path: Path) -> None:
    """UTF-8 source files with a BOM remain parseable."""
    relative = Path("src/decoder.py")
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text("\ufeffimport json\njson.loads(text)\n", encoding="utf-8")

    findings = check_json_structure(
        tmp_path,
        [relative],
        SourceScanPolicy(extensions=[".py"], exclude=[]),
    )

    assert [(finding.path, finding.line, finding.rule_id) for finding in findings] == [
        ("src/decoder.py", 2, "data.json-structure")
    ]
