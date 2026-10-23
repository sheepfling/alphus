from pathlib import Path

from scripts.ci import dependency_floors


def test_ci_dependency_floors_follow_package_metadata() -> None:
    assert dependency_floors(Path("pyproject.toml")) == (
        "packaging==23",
        "pydantic==2.7",
        "rich==15.0.0",
        "typer==0.27.3",
        "pyright==1.1.414",
        "pytest==8",
        "ruff==0.16",
    )
