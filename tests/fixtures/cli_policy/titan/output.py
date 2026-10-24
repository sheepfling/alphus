"""Shared synthetic renderer and serializer used by the TITAN regression map."""

import json

from rich.console import Console


def render_doctor(report: object, console: Console) -> None:
    console.print(report)


def serialize_doctor(report: object) -> str:
    return json.dumps(report, default=str)


def render_shared(report: object, console: Console) -> None:
    console.print(report)
