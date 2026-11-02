"""The pinned consumer calibration must only create isolated fixture copies."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "prepare_mdutils_stub_trial.py"
)
SPEC = importlib.util.spec_from_file_location("prepare_mdutils_stub_trial", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
prepare_mdutils_stub_trial = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare_mdutils_stub_trial
SPEC.loader.exec_module(prepare_mdutils_stub_trial)


def _consumer(root: Path) -> tuple[bytes, bytes]:
    (root / "mdutils-stubs").mkdir(parents=True)
    (root / "mdutils-stubs" / "__init__.pyi").write_text(
        "class MdUtils: ...\n", encoding="utf-8"
    )
    (root / "tests" / "fixtures").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "mdutils-stubs"\n'
        'dependencies = ["mdutils==1.8.1"]\nlicense = "MIT"\n',
        encoding="utf-8",
    )
    (root / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    positive = (
        b"assert_type(document.textUtils, type[TextUtilsClass])\n"
        b"assert_type(mdutils.TextUtils, type[TextUtilsClass])\n"
        b"assert_type(ToolsTextUtils, type[TextUtilsClass])\n"
    )
    negative = (
        b"from mdutils import MdUtils, TextUtils\n\n"
        b"document = MdUtils(file_name=42)\n"
        b'document.new_header(level="first", title=7)\n'
        b"document.new_table(columns=1, rows=1, text=[7], text_align=4)\n"
        b"TextUtils.text_format(text=42)\n"
    )
    (root / "tests" / "fixtures" / "positive.py").write_bytes(positive)
    (root / "tests" / "fixtures" / "negative.py").write_bytes(negative)
    return positive, negative


def test_preparation_keeps_original_fixtures_and_stub_tree_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    positive, negative = _consumer(tmp_path)
    package_before = prepare_mdutils_stub_trial._package_digest(tmp_path)
    monkeypatch.setattr(
        prepare_mdutils_stub_trial.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["git"], 0, prepare_mdutils_stub_trial.CONSUMER_REVISION + "\n", ""
        ),
    )

    prepare_mdutils_stub_trial.prepare(tmp_path)

    assert (tmp_path / "tests/fixtures/positive.py").read_bytes() == positive
    assert (tmp_path / "tests/fixtures/negative.py").read_bytes() == negative
    assert prepare_mdutils_stub_trial._package_digest(tmp_path) == package_before
    calibrated_positive = (
        tmp_path / "tests/fixtures/positive_calibrated.py"
    ).read_text()
    assert (
        "document_text_utils: type[TextUtilsClass] = document.textUtils"
        in calibrated_positive
    )
    calibrated_negative = (
        tmp_path / "tests/fixtures/negative_calibrated.py"
    ).read_text()
    assert calibrated_negative.count("# expect-error") == 4
    assert '"typing_checkers": [' in (tmp_path / "stub-quality.json").read_text()
    assert (tmp_path / "tests/__init__.py").is_file()


def test_preparation_rejects_an_unreviewed_negative_fixture_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _consumer(tmp_path)
    (tmp_path / "tests/fixtures/negative.py").write_text(
        "from mdutils import MdUtils\n\nMdUtils()\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        prepare_mdutils_stub_trial.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["git"], 0, prepare_mdutils_stub_trial.CONSUMER_REVISION + "\n", ""
        ),
    )

    with pytest.raises(ValueError, match="negative fixture differs"):
        prepare_mdutils_stub_trial.prepare(tmp_path)
