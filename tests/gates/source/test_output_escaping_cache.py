"""Persistent output-escaping cache invalidation and equivalence tests."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Never

import pytest
from typer.testing import CliRunner

from alphus.cli import app, main
from alphus.config import SourceScanPolicy
from alphus.gates.source import output_escaping_cache
from alphus.gates.source.output_escaping import check_output_escaping
from alphus.gates.source.output_escaping_cache import check_output_escaping_cached


def _source(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return Path(name)


def _policy(*, exclude: tuple[str, ...] = ()) -> SourceScanPolicy:
    return SourceScanPolicy(extensions=(".py", ".js"), exclude=exclude)


def test_warm_cache_matches_uncached_results_and_skips_file_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(
        tmp_path,
        "src/render.py",
        'value = value.replace("<", "&lt;")\n',
    )
    cache = tmp_path / ".alphus-cache" / "output-escaping.json"
    expected = check_output_escaping(tmp_path, [source], _policy())

    cold_findings, cold = check_output_escaping_cached(
        tmp_path, [source], _policy(), cache
    )
    assert cold_findings == expected
    assert (cold.hits, cold.misses, cold.pruned, cold.saved) == (0, 1, 0, True)

    def unexpected_analysis(_relative: Path, _source: str) -> Never:
        raise AssertionError("a valid warm hit must skip source analysis")

    monkeypatch.setattr(
        output_escaping_cache,
        "output_escaping_findings_for_source",
        unexpected_analysis,
    )
    warm_findings, warm = check_output_escaping_cached(
        tmp_path, [source], _policy(), cache
    )
    assert warm_findings == expected
    assert (warm.hits, warm.misses, warm.pruned, warm.saved) == (1, 0, 0, True)


def test_cache_recomputes_after_same_path_content_changes(tmp_path: Path) -> None:
    source = _source(tmp_path, "src/render.py", "value = html.escape(value)\n")
    cache = tmp_path / "cache.json"
    first, _ = check_output_escaping_cached(tmp_path, [source], _policy(), cache)
    assert first == []

    (tmp_path / source).write_text(
        'value = value.replace("|", "\\\\|")\n', encoding="utf-8"
    )
    updated, summary = check_output_escaping_cached(
        tmp_path, [source], _policy(), cache
    )

    assert updated == check_output_escaping(tmp_path, [source], _policy())
    assert len(updated) == 1
    assert (summary.hits, summary.misses) == (0, 1)


def test_inventory_addition_and_deletion_reuse_only_retained_paths(
    tmp_path: Path,
) -> None:
    first = _source(tmp_path, "src/first.py", "value = html.escape(value)\n")
    deleted = _source(tmp_path, "src/deleted.py", "value = html.escape(value)\n")
    cache = tmp_path / "cache.json"
    check_output_escaping_cached(tmp_path, [first, deleted], _policy(), cache)

    (tmp_path / deleted).unlink()
    added = _source(tmp_path, "src/added.py", 'value = value.replace("<", "&lt;")\n')
    actual, summary = check_output_escaping_cached(
        tmp_path, [first, added], _policy(), cache
    )

    assert actual == check_output_escaping(tmp_path, [first, added], _policy())
    assert (summary.hits, summary.misses, summary.pruned) == (1, 1, 1)


def test_policy_change_invalidates_all_cached_findings(tmp_path: Path) -> None:
    source = _source(tmp_path, "src/render.py", 'value = value.replace("<", "&lt;")\n')
    cache = tmp_path / "cache.json"
    check_output_escaping_cached(tmp_path, [source], _policy(), cache)

    actual, summary = check_output_escaping_cached(
        tmp_path, [source], _policy(exclude=("src/**",)), cache
    )

    assert actual == check_output_escaping(
        tmp_path, [source], _policy(exclude=("src/**",))
    )
    assert actual == []
    assert (summary.hits, summary.misses) == (0, 0)
    assert summary.invalidation == "root, policy, schema, or rule version changed"


def test_rule_version_change_invalidates_cache(tmp_path: Path) -> None:
    source = _source(tmp_path, "src/render.py", "value = html.escape(value)\n")
    cache = tmp_path / "cache.json"
    check_output_escaping_cached(tmp_path, [source], _policy(), cache)
    payload = json.loads(cache.read_text(encoding="utf-8"))
    payload["header"]["rule_version"] = 0
    cache.write_text(json.dumps(payload), encoding="utf-8")

    actual, summary = check_output_escaping_cached(tmp_path, [source], _policy(), cache)

    assert actual == check_output_escaping(tmp_path, [source], _policy())
    assert (summary.hits, summary.misses) == (0, 1)
    assert summary.invalidation == "root, policy, schema, or rule version changed"


@pytest.mark.parametrize("duplicate_scope", ["top-level", "nested"])
def test_duplicate_cache_keys_are_rejected_and_recomputed(
    tmp_path: Path, duplicate_scope: str
) -> None:
    source = _source(tmp_path, "src/render.py", 'value = value.replace("<", "&lt;")\n')
    cache = tmp_path / "cache.json"
    check_output_escaping_cached(tmp_path, [source], _policy(), cache)
    payload = json.loads(cache.read_text(encoding="utf-8"))
    encoded = json.dumps(payload)
    if duplicate_scope == "top-level":
        encoded = encoded.replace('"entries":', '"header":{},"entries":')
    else:
        encoded = encoded.replace(
            '"content_sha256":',
            '"content_sha256":"' + "0" * 64 + '","content_sha256":',
            1,
        )
    cache.write_text(encoded, encoding="utf-8")

    actual, summary = check_output_escaping_cached(tmp_path, [source], _policy(), cache)

    assert actual == check_output_escaping(tmp_path, [source], _policy())
    assert (summary.hits, summary.misses) == (0, 1)
    assert summary.invalidation == "cache is unreadable or invalid"


@pytest.mark.parametrize("malformation", ["digest", "finding", "extra-field"])
def test_malformed_cache_entries_are_discarded_and_recomputed(
    tmp_path: Path, malformation: str
) -> None:
    source = _source(tmp_path, "src/render.py", 'value = value.replace("<", "&lt;")\n')
    cache = tmp_path / "cache.json"
    expected = check_output_escaping_cached(tmp_path, [source], _policy(), cache)[0]
    payload = json.loads(cache.read_text(encoding="utf-8"))
    entry = payload["entries"]["src/render.py"]
    if malformation == "digest":
        entry["content_sha256"] = "not-a-sha256"
    elif malformation == "finding":
        entry["findings"][0]["severity"] = "unrecognized"
    else:
        entry["unexpected"] = True
    cache.write_text(json.dumps(payload), encoding="utf-8")

    actual, summary = check_output_escaping_cached(tmp_path, [source], _policy(), cache)

    assert actual == expected == check_output_escaping(tmp_path, [source], _policy())
    assert (summary.hits, summary.misses) == (0, 1)
    assert summary.invalidation == "cache schema or entries are invalid"


@pytest.mark.parametrize("identity_field", ["path", "rule_id"])
def test_valid_cache_entry_with_wrong_finding_identity_is_recomputed(
    tmp_path: Path, identity_field: str
) -> None:
    source = _source(tmp_path, "src/render.py", 'value = value.replace("<", "&lt;")\n')
    cache = tmp_path / "cache.json"
    expected = check_output_escaping_cached(tmp_path, [source], _policy(), cache)[0]
    payload = json.loads(cache.read_text(encoding="utf-8"))
    finding = payload["entries"]["src/render.py"]["findings"][0]
    finding[identity_field] = (
        "src/other.py"
        if identity_field == "path"
        else "alphus/python/none/security/different-rule"
    )
    cache.write_text(json.dumps(payload), encoding="utf-8")

    actual, summary = check_output_escaping_cached(tmp_path, [source], _policy(), cache)
    warm, warm_summary = check_output_escaping_cached(
        tmp_path, [source], _policy(), cache
    )

    assert actual == expected == check_output_escaping(tmp_path, [source], _policy())
    assert (summary.hits, summary.misses) == (0, 1)
    assert summary.invalidation == "cached finding identity changed"
    assert warm == expected
    assert (warm_summary.hits, warm_summary.misses) == (1, 0)


def test_force_fresh_bypasses_warm_entries_and_replaces_them(tmp_path: Path) -> None:
    source = _source(tmp_path, "src/render.py", "value = html.escape(value)\n")
    cache = tmp_path / "cache.json"
    check_output_escaping_cached(tmp_path, [source], _policy(), cache)

    actual, summary = check_output_escaping_cached(
        tmp_path, [source], _policy(), cache, force_fresh=True
    )
    next_run, next_summary = check_output_escaping_cached(
        tmp_path, [source], _policy(), cache
    )

    assert actual == next_run == check_output_escaping(tmp_path, [source], _policy())
    assert (summary.hits, summary.misses, summary.force_fresh) == (0, 1, True)
    assert (next_summary.hits, next_summary.misses) == (1, 0)


def test_cli_reports_cache_status_on_stderr_without_changing_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    _source(tmp_path, "src/render.py", 'value = value.replace("<", "&lt;")\n')
    config = tmp_path / "quality-gates.toml"
    config.write_text(
        "schema_version = 1\n"
        '[files]\ninclude = ["src/**"]\nexclude = []\n'
        '[checks.output_escaping]\nextensions = [".py"]\nexclude = []\n',
        encoding="utf-8",
    )
    cache = tmp_path / ".alphus-cache" / "output-escaping.json"
    arguments = [
        "--root",
        str(tmp_path),
        "--config",
        str(config),
        "--rule",
        "output-escaping",
        "--local-cache",
        str(cache),
        "--json",
    ]

    assert main(arguments) == 1
    cold = capsys.readouterr()
    cold_json = json.loads(cold.out)
    assert len(cold_json) == 1
    assert "0 hit(s), 1 miss(es)" in cold.err

    assert main(arguments) == 1
    warm = capsys.readouterr()
    assert json.loads(warm.out) == cold_json
    assert "1 hit(s), 0 miss(es)" in warm.err


def test_cli_restricts_cache_and_force_fresh_to_direct_output_rule(
    tmp_path: Path,
) -> None:
    def plain(output: str) -> str:
        without_ansi = re.sub(r"\x1b\[[0-9;]*m", "", output)
        without_boxes = without_ansi.translate(str.maketrans("│╭╮╰╯─", "      "))
        return " ".join(without_boxes.split())

    runner = CliRunner()
    missing_cache = runner.invoke(app, ["--force-fresh"], color=False)
    assert missing_cache.exit_code == 2
    assert "Invalid value" in missing_cache.output
    missing_message = plain(missing_cache.output)
    assert "--force-fresh requires --local-cache" in missing_message

    unsupported_rule = runner.invoke(
        app,
        [
            "--rule",
            "line-length",
            "--local-cache",
            str(tmp_path / "cache.json"),
        ],
        color=False,
        terminal_width=160,
    )
    assert unsupported_rule.exit_code == 2
    assert "Invalid value" in unsupported_rule.output
    unsupported_message = plain(unsupported_rule.output)
    assert "limited to a direct --rule output-escaping run" in unsupported_message

    help_result = runner.invoke(app, ["--help"], color=False)
    assert help_result.exit_code == 0
    help_text = plain(help_result.output)
    assert "--local-cache" in help_text
    assert "--force-fresh" in help_text
