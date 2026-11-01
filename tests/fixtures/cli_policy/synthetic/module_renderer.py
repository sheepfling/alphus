"""Synthetic command that uses a module-level Rich Console instance."""

import json

import typer
from rich.console import Console

app = typer.Typer()
console = Console()


@app.command()
def command_uses_module_renderer(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        console.print("ready")


if __name__ == "__main__":
    app()
