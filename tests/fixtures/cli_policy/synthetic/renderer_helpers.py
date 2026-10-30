"""Synthetic renderer and serializer helpers shared by CLI controls."""

import json

from rich.console import Console


def render_report(report: object, console: Console) -> None:
    console.print(report)


def serialize_report(report: object) -> str:
    return json.dumps(report, default=str)


def render_shared(report: object, console: Console) -> None:
    console.print(report)
