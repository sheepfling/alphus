"""Consumer CLI with a file output and a separate human presentation choice."""

import json
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console

app = typer.Typer()


@app.command()
def report(
    output: Annotated[Path, typer.Option("--output", help="Write a JSON report.")],
    output_style: Annotated[
        Literal["plain", "rich"], typer.Option("--output-style")
    ] = "rich",
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    payload = {"status": "ready"}
    output.write_text(json.dumps(payload), encoding="utf-8")
    if json_output:
        typer.echo(json.dumps(payload))
    elif output_style == "rich":
        Console().print("Ready")
    else:
        typer.echo("Ready")


if __name__ == "__main__":
    app()
