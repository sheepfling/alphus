"""Synthetic commands that delegate presentation to one imported renderer."""

import json

import typer
from rich.console import Console
from synthetic.renderer_helpers import render_shared

app = typer.Typer()


@app.command()
def command_1(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        render_shared("ready", Console())


@app.command()
def command_2(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        render_shared("ready", Console())


@app.command()
def command_3(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        render_shared("ready", Console())


@app.command()
def command_4(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        render_shared("ready", Console())


@app.command()
def command_5(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        render_shared("ready", Console())


if __name__ == "__main__":
    app()
