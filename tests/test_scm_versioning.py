"""Verify tag-derived versions and rebuilds from Git-less source archives."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from packaging.utils import parse_wheel_filename
from packaging.version import Version


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


def _successful_run(
    command: Sequence[str], *, cwd: Path, env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    result = _run(command, cwd=cwd, env=env)
    assert result.returncode == 0, result.stderr
    return result


def _scm_version(
    root: Path, *, env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "-m", "setuptools_scm"], cwd=root, env=env)


def _build(
    root: Path,
    output: Path,
    build_kind: str,
    *,
    env: Mapping[str, str],
) -> list[Path]:
    output.mkdir()
    _successful_run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            f"--{build_kind}",
            "--outdir",
            str(output),
            str(root),
        ],
        cwd=root,
        env=env,
    )
    return list(output.glob(f"alphus-*.{'whl' if build_kind == 'wheel' else 'tar.gz'}"))


def _wheel_version(wheel: Path) -> Version:
    distribution, version, _build, _tags = parse_wheel_filename(wheel.name)
    assert distribution == "alphus"
    return version


def _extract(
    archive_path: Path, destination: Path, *, single_root: bool = True
) -> Path:
    destination.mkdir()
    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        roots = {member.name.split("/", maxsplit=1)[0] for member in members}
        if single_root:
            assert len(roots) == 1
        archive.extractall(destination, filter="data")
    return destination / roots.pop() if single_root else destination


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("SETUPTOOLS_SCM_PRETEND"):
            environment.pop(name)
    return environment


def test_tagged_and_archived_builds_keep_the_same_version(
    tmp_path: Path, pytestconfig: pytest.Config
) -> None:
    project = Path(pytestconfig.rootpath)
    environment = _clean_environment()
    repository = tmp_path / "scm-repository"
    source = repository / "src" / "alphus"
    source.mkdir(parents=True)
    for relative in (
        "pyproject.toml",
        "README.md",
        ".gitattributes",
        ".git_archival.txt",
        "MANIFEST.in",
    ):
        shutil.copy2(project / relative, repository / relative)
    (source / "__init__.py").write_text('"""Version fixture."""\n', encoding="utf-8")

    _successful_run(["git", "init", "--quiet"], cwd=repository, env=environment)
    _successful_run(
        ["git", "config", "user.name", "Alphus SCM test"],
        cwd=repository,
        env=environment,
    )
    _successful_run(
        ["git", "config", "user.email", "alphus-scm@example.invalid"],
        cwd=repository,
        env=environment,
    )
    _successful_run(["git", "add", "."], cwd=repository, env=environment)
    _successful_run(
        ["git", "commit", "--quiet", "-m", "version fixture"],
        cwd=repository,
        env=environment,
    )
    _successful_run(["git", "tag", "0.0.2"], cwd=repository, env=environment)

    exact_tag = _scm_version(repository, env=environment)
    assert exact_tag.returncode == 0, exact_tag.stderr
    assert exact_tag.stdout.strip() == "0.0.2"
    tagged_wheels = _build(
        repository, tmp_path / "tagged-wheel", "wheel", env=environment
    )
    assert len(tagged_wheels) == 1
    assert _wheel_version(tagged_wheels[0]) == Version("0.0.2")

    _successful_run(
        [
            "git",
            "-c",
            "user.name=Alphus SCM test",
            "-c",
            "user.email=alphus-scm@example.invalid",
            "commit",
            "--allow-empty",
            "--quiet",
            "-m",
            "post-tag commit",
        ],
        cwd=repository,
        env=environment,
    )
    post_tag = _scm_version(repository, env=environment)
    assert post_tag.returncode == 0, post_tag.stderr
    post_tag_version = Version(post_tag.stdout.strip())
    assert post_tag_version.public == "0.0.3.dev1"
    assert post_tag_version.local is not None

    git_wheels = _build(repository, tmp_path / "git-wheel", "wheel", env=environment)
    assert len(git_wheels) == 1
    assert _wheel_version(git_wheels[0]) == post_tag_version

    archive = tmp_path / "git-archive.tar"
    with archive.open("wb") as output:
        completed = subprocess.run(
            ["git", "archive", "--format=tar", "HEAD"],
            cwd=repository,
            env=environment,
            stdout=output,
            stderr=subprocess.PIPE,
            check=False,
        )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    archived_source = _extract(
        archive, tmp_path / "git-archive-source", single_root=False
    )
    assert not (archived_source / ".git").exists()
    archived_version = _scm_version(archived_source, env=environment)
    assert archived_version.returncode == 0, archived_version.stderr
    archived_package_version = Version(archived_version.stdout.strip())
    assert archived_package_version.public == post_tag_version.public
    assert archived_package_version.local is not None
    archived_wheels = _build(
        archived_source, tmp_path / "archive-wheel", "wheel", env=environment
    )
    assert len(archived_wheels) == 1
    assert _wheel_version(archived_wheels[0]).public == post_tag_version.public

    sdists = _build(repository, tmp_path / "sdist", "sdist", env=environment)
    assert len(sdists) == 1
    unpacked_sdist = _extract(sdists[0], tmp_path / "sdist-source")
    assert not (unpacked_sdist / ".git").exists()
    sdist_version = _scm_version(unpacked_sdist, env=environment)
    assert sdist_version.returncode == 0, sdist_version.stderr
    assert Version(sdist_version.stdout.strip()) == post_tag_version
    sdist_wheels = _build(
        unpacked_sdist, tmp_path / "sdist-wheel", "wheel", env=environment
    )
    assert len(sdist_wheels) == 1
    assert _wheel_version(sdist_wheels[0]) == post_tag_version

    shallow = tmp_path / "shallow-clone"
    _successful_run(
        ["git", "clone", "--quiet", "--depth=1", repository.as_uri(), str(shallow)],
        cwd=tmp_path,
        env=environment,
    )
    shallow_version = _scm_version(shallow, env=environment)
    assert shallow_version.returncode != 0
    assert "shallow" in shallow_version.stderr.lower()

    raw_source = tmp_path / "raw-source-without-version-metadata"
    shutil.copytree(
        repository,
        raw_source,
        ignore=shutil.ignore_patterns(
            ".git", ".git_archival.txt", "*.egg-info", "build", "dist"
        ),
    )
    raw_version = _scm_version(raw_source, env=environment)
    assert raw_version.returncode != 0
