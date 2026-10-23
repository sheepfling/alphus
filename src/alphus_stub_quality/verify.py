"""Compatibility import and module entry point for stub verification."""

from alphus.gates.stubs.verify import *  # noqa: F403
from alphus.gates.stubs.verify import main

if __name__ == "__main__":
    raise SystemExit(main())
