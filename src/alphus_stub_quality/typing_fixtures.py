"""Compatibility import and module entry point for typing fixture checks."""

from alphus.gates.stubs.typing_fixtures import *  # noqa: F403
from alphus.gates.stubs.typing_fixtures import main

if __name__ == "__main__":
    raise SystemExit(main())
