"""Exercise the dynamic Markdown CLI from the built distribution artifact."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import venv
from collections.abc import Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest
from packaging.version import Version

from alphus.support.platform_utils import is_windows


def _dependency_overlay(source: Path, target: Path) -> None:
    """Expose test-runtime dependencies without exposing editable Alphus."""
    target.mkdir()
    for item in source.iterdir():
        if item.name.startswith("alphus") or item.suffix == ".pth":
            continue
        link = target / item.name
        try:
            link.symlink_to(item, target_is_directory=item.is_dir())
        except OSError:
            if item.is_dir():
                shutil.copytree(item, link)
            else:
                shutil.copy2(item, link)


def _run(
    command: Sequence[str], *, cwd: Path, env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_built_wheel_cli_uses_git_inventory_and_respects_scope(
    tmp_path: Path, pytestconfig: pytest.Config
) -> None:
    project = pytestconfig.rootpath
    isolated_env = os.environ.copy()
    isolated_env.pop("PYTHONPATH", None)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    build_command = [sys.executable, "-m", "pip", "wheel", "--no-deps"]
    try:
        setuptools_version = Version(version("setuptools"))
    except PackageNotFoundError:
        pass
    else:
        if setuptools_version >= Version("68"):
            build_command.append("--no-build-isolation")
    build_command.extend(["--wheel-dir", str(wheelhouse), str(project)])
    built = _run(
        build_command,
        cwd=project,
        env=isolated_env,
    )
    assert built.returncode == 0, built.stderr
    wheels = tuple(wheelhouse.glob("alphus-*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]

    environment = tmp_path / "installed"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if is_windows() else "bin/python")
    cli = environment / ("Scripts/alphus.exe" if is_windows() else "bin/alphus")
    install = _run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
        cwd=project,
        env=isolated_env,
    )
    assert install.returncode == 0, install.stderr

    dependency_site = Path(sysconfig.get_paths()["purelib"])
    dependencies = tmp_path / "runtime-dependencies"
    _dependency_overlay(dependency_site, dependencies)
    env = isolated_env.copy()
    env["PYTHONPATH"] = str(dependencies)

    identity_process = _run(
        [
            str(python),
            "-c",
            (
                "import alphus, importlib.metadata, json; "
                "print(json.dumps({'module': alphus.__file__, "
                "'version': importlib.metadata.version('alphus')}))"
            ),
        ],
        cwd=tmp_path,
        env=env,
    )
    assert identity_process.returncode == 0, identity_process.stderr
    identity = json.loads(identity_process.stdout)
    site_packages = environment / (
        Path("Lib/site-packages")
        if is_windows()
        else Path(
            f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
        )
    )
    assert (
        Path(identity["module"])
        .resolve()
        .is_relative_to((site_packages / "alphus").resolve())
    )
    assert identity["version"] == "0.0.2"
    wheel_sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()
    identity_record = {
        "wheel": wheel.name,
        "wheel_sha256": wheel_sha256,
        **identity,
    }
    (tmp_path / "installed-wheel-identity.json").write_text(
        json.dumps(identity_record, indent=2) + "\n", encoding="utf-8"
    )

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    subprocess.run(["git", "init", "--quiet", str(consumer)], check=True)
    subprocess.run(
        ["git", "-C", str(consumer), "config", "user.name", "Alphus smoke test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(consumer),
            "config",
            "user.email",
            "alphus-smoke@example.invalid",
        ],
        check=True,
    )
    included = consumer / "scripts/generate_notes.py"
    included.parent.mkdir(parents=True)
    included.write_text(
        'def render(value):\n    return f"| {value} |\\n"\n',
        encoding="utf-8",
    )
    excluded = consumer / "scripts/generated/render.py"
    excluded.parent.mkdir(parents=True)
    excluded.write_text(included.read_text(encoding="utf-8"), encoding="utf-8")
    config = consumer / "quality.toml"
    config.write_text(
        """schema_version = 1

[files]
include = ["scripts/**/*.py"]
exclude = []

[checks.dynamic_markdown]
extensions = [".py"]
producer_paths = ["scripts/**"]
exclude = ["scripts/generated/**"]

[orchestration]
default_profile = "markdown-review"

[[orchestration.steps]]
kind = "rule"
name = "Markdown source review"
rule = "dynamic-markdown"

[[orchestration.profiles]]
name = "markdown-review"
steps = ["Markdown source review"]
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(consumer), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(consumer), "commit", "--quiet", "-m", "consumer fixture"],
        check=True,
    )

    common = [
        str(cli),
        "--root",
        str(consumer),
        "--config",
        str(config),
        "--run",
        "--profile",
        "markdown-review",
    ]
    json_run = _run([*common, "--json"], cwd=tmp_path, env=env)
    assert json_run.returncode == 0, json_run.stderr
    payload = json.loads(json_run.stdout)
    findings = [
        finding for step in payload["steps"] for finding in step.get("findings", [])
    ]
    assert len(findings) == 1
    assert findings[0]["path"] == "scripts/generate_notes.py"
    assert findings[0]["line"] == 2
    assert findings[0]["rule_id"].endswith("dynamic-markdown-assembly")
    assert "table cell" in findings[0]["message"]
    assert all("scripts/generated/" not in item["path"] for item in findings)

    text_run = _run(common, cwd=tmp_path, env=env)
    assert text_run.returncode == 0, text_run.stderr
    assert "scripts/generate_notes.py" in text_run.stdout
    assert "table cell" in text_run.stdout
    assert "scripts/generated/render.py" not in text_run.stdout
