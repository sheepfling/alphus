"""Synthetic commands that pass typed Rich consoles through a local helper."""

import json

import typer
from rich.console import Console

app = typer.Typer()


def _render(report: object, console: Console) -> None:
    console.print(report)


@app.command()
def command_1(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        _render("ready", Console())


@app.command()
def command_2(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        _render("ready", Console())


@app.command()
def command_3(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        _render("ready", Console())


@app.command()
def command_4(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        _render("ready", Console())


@app.command()
def command_5(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        _render("ready", Console())


if __name__ == "__main__":
    app()
