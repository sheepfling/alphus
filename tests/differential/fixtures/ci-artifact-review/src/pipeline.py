from collections.abc import Sequence
from pathlib import Path


def write_output(output_path: Path, rows: Sequence[str]) -> None:
    pass


def read_output(output_path: Path) -> Sequence[str]:
    return ()


def publish(rows: Sequence[str]) -> None:
    pass


def build(rows: Sequence[str], output_path: Path) -> None:
    if rows:
        write_output(output_path, rows)
    publish(read_output(output_path))
