"""Synthetic command that delegates rendering and serialization."""

import typer
from rich.console import Console
from synthetic.renderer_helpers import render_report, serialize_report

app = typer.Typer()


@app.command()
def command_uses_imported_helpers(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(serialize_report({"ready": True}))
    else:
        render_report("ready", Console())


if __name__ == "__main__":
    app()
