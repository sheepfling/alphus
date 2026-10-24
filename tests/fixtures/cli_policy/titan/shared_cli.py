"""Commands whose output is rendered by a uniquely resolved imported helper."""

import json

import typer
from rich.console import Console
from titan.output import render_shared

app = typer.Typer()


@app.command()
def dis_network_send(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        render_shared("ready", Console())


@app.command()
def dis_network_receive(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        render_shared("ready", Console())


@app.command()
def dis_network_interop(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        render_shared("ready", Console())


@app.command()
def dis_soak_test(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        render_shared("ready", Console())


@app.command()
def offline_map_pack_audit(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(json.dumps({"ready": True}))
    else:
        render_shared("ready", Console())


if __name__ == "__main__":
    app()
