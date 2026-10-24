"""Commands whose renderer evidence reaches typed local helpers."""

import json

import typer
from rich.console import Console

app = typer.Typer()


def _render(report: object, console: Console) -> None:
    console.print(report)


@app.command()
def deployment_acceptance(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        _render("ready", Console())


@app.command()
def grill(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        _render("ready", Console())


@app.command()
def install_test_classes(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        _render("ready", Console())


@app.command()
def stream_titan_mission(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        _render("ready", Console())


@app.command()
def taoryx_compatibility(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        _render("ready", Console())


if __name__ == "__main__":
    app()
