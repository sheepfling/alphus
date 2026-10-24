"""Doctor CLI with imported renderer and serializer helpers."""

import typer
from rich.console import Console
from titan.output import render_doctor, serialize_doctor

app = typer.Typer()


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if json_output:
        typer.echo(serialize_doctor({"ready": True}))
    else:
        render_doctor("ready", Console())


if __name__ == "__main__":
    app()
