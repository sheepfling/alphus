"""Guard the reusable GitLab job's Git inventory bootstrap."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def test_gitlab_template_provisions_and_smokes_default_git_inventory(
    pytestconfig: pytest.Config,
) -> None:
    root = Path(pytestconfig.rootpath)
    template = yaml.safe_load(
        (root / "ci/gitlab/quality.yml").read_text(encoding="utf-8")
    )
    job = template[".alphus-quality"]

    assert job["image"] == "python:3.12-slim"
    script = "\n".join(job["script"])
    assert "CI_JOB_IMAGE" in script
    assert "apt-get install -y --no-install-recommends git" in script
    assert "Git is missing from custom GitLab image" in script
    assert 'git -C "$CI_PROJECT_DIR" ls-files' in script
    assert "ALPHUS_REQUIREMENTS_FILE" in script
    assert "ALPHUS_RUNTIME_REQUIREMENTS_FILE" in script
    assert "Git is required by Alphus file-scoped checks" in script

    smoke = script.index("from alphus.support.inventory import git_files")
    profile = script.index("python -m alphus --root")
    assert smoke < profile
    assert "paths = git_files(root)" in script
    assert "Git-backed inventory smoke check found" in script
