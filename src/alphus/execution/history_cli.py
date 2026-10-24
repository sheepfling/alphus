"""CLI for rebuilding and querying a local cross-repository quality index."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.json import JSON
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from alphus.contracts.model import StrictModel
from alphus.execution.history_index import (
    ingest_archives,
    list_gate_observations,
    list_index_runs,
    open_index,
    portfolio_rollup,
)

app = typer.Typer(help="Analyze verified Alphus archives across consumers.")
JsonOption = Annotated[bool, typer.Option("--json", help="Emit one JSON value.")]
OutputOption = Annotated[
    Literal["auto", "plain", "rich", "json"],
    typer.Option("--output", help="Output: auto, plain, rich, or json."),
]
VerboseOption = Annotated[
    bool, typer.Option("--verbose", help="Write progress to stderr.")
]


def _render(result: StrictModel, *, json_output: bool, output: str) -> None:
    if output not in {"auto", "plain", "rich", "json"}:
        raise ValueError("--output must be auto, plain, rich, or json")
    if json_output and output not in {"auto", "json"}:
        raise ValueError("--json cannot be combined with --output plain or rich")
    encoded = result.model_dump_json(indent=2)
    if (
        json_output
        or output in {"plain", "json"}
        or (output == "auto" and not sys.stdout.isatty())
    ):
        typer.echo(encoded)
    else:
        Console().print(JSON(encoded))


def _execute(
    database: Path,
    operation: Callable[[Engine], StrictModel],
    *,
    json_output: bool,
    output: str,
    verbose: bool,
    create: bool = False,
) -> None:
    try:
        if not create and not database.is_file():
            raise ValueError(f"database does not exist: {database}")
        engine = open_index(database)
        try:
            result = operation(engine)
        finally:
            engine.dispose()
        _render(result, json_output=json_output, output=output)
        if verbose:
            Console(stderr=True).print(f"Indexed database: {database}")
    except (OSError, SQLAlchemyError, TypeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error


@app.command("ingest")
def ingest_command(
    database: Annotated[Path, typer.Option("--database")],
    archive: Annotated[list[Path], typer.Option("--archive")],
    json_output: JsonOption = False,
    output: OutputOption = "auto",
    verbose: VerboseOption = False,
) -> None:
    """Index one or more immutable JSON archives."""
    if not archive:
        raise typer.BadParameter("at least one --archive is required")
    _execute(
        database,
        lambda engine: ingest_archives(engine, archive),
        json_output=json_output,
        output=output,
        verbose=verbose,
        create=True,
    )


@app.command("rollup")
def rollup_command(
    database: Annotated[Path, typer.Option("--database")],
    consumer_id: Annotated[str | None, typer.Option("--consumer-id")] = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    gate_id: Annotated[str | None, typer.Option("--gate-id")] = None,
    json_output: JsonOption = False,
    output: OutputOption = "auto",
    verbose: VerboseOption = False,
) -> None:
    """Summarize coverage, failures, and timing by gate policy."""
    _execute(
        database,
        lambda engine: portfolio_rollup(
            engine, consumer_id=consumer_id, profile=profile, gate_id=gate_id
        ),
        json_output=json_output,
        output=output,
        verbose=verbose,
    )


@app.command("runs")
def runs_command(
    database: Annotated[Path, typer.Option("--database")],
    consumer_id: Annotated[str | None, typer.Option("--consumer-id")] = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    offset: Annotated[int, typer.Option("--offset")] = 0,
    limit: Annotated[int, typer.Option("--limit")] = 100,
    json_output: JsonOption = False,
    output: OutputOption = "auto",
    verbose: VerboseOption = False,
) -> None:
    """Page through indexed runs and their archive paths."""
    _execute(
        database,
        lambda engine: list_index_runs(
            engine,
            consumer_id=consumer_id,
            profile=profile,
            offset=offset,
            limit=limit,
        ),
        json_output=json_output,
        output=output,
        verbose=verbose,
    )


@app.command("gates")
def gates_command(
    database: Annotated[Path, typer.Option("--database")],
    consumer_id: Annotated[str | None, typer.Option("--consumer-id")] = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    gate_id: Annotated[str | None, typer.Option("--gate-id")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    offset: Annotated[int, typer.Option("--offset")] = 0,
    limit: Annotated[int, typer.Option("--limit")] = 100,
    json_output: JsonOption = False,
    output: OutputOption = "auto",
    verbose: VerboseOption = False,
) -> None:
    """Page through individual gate outcomes for triage."""
    _execute(
        database,
        lambda engine: list_gate_observations(
            engine,
            consumer_id=consumer_id,
            profile=profile,
            gate_id=gate_id,
            status=status,
            offset=offset,
            limit=limit,
        ),
        json_output=json_output,
        output=output,
        verbose=verbose,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Typer application and return a shell-friendly status."""
    try:
        app(args=list(argv) if argv is not None else None, standalone_mode=False)
    except typer.BadParameter as error:
        typer.echo(f"alphus-history: {error.format_message()}", err=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
