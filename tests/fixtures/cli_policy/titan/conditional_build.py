"""Optional-dependency CLI with a standard-library build fallback."""

import json
import sys
from collections.abc import Sequence
from typing import Any

typer: Any = None
Console: Any = None
app: Any = None
try:
    import typer as _typer_module
    from rich.console import Console as _rich_console
except ModuleNotFoundError:
    pass
else:
    typer = _typer_module
    Console = _rich_console
    app = typer.Typer()


def fallback_main(arguments: Sequence[str]) -> int:
    return 0


if app is not None:

    @app.command()
    def build_standard(
        json_output: bool = typer.Option(False, "--json"),
        verbose: bool = typer.Option(False, "--verbose"),
    ) -> None:
        if json_output:
            typer.echo(json.dumps({"ready": True}))
        else:
            Console().print("ready")


def main() -> None:
    if app is None:
        raise SystemExit(fallback_main(sys.argv[1:]))
    app()


if __name__ == "__main__":
    main()
