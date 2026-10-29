"""Command line interface for planned compatibility import checks."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from alphus.gates.python.compatibility import check_forwarders


def main(argv: Sequence[str] | None = None) -> int:
    """Check forwarding modules and report their removal commitments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    options = parser.parse_args(argv)
    try:
        issues, planned = check_forwarders(options.source_root, options.plan)
    except OSError as error:
        print(f"Python compatibility imports: {error}", file=sys.stderr)
        return 2
    for entry in planned:
        print(f"PLAN {entry}")
    for issue in issues:
        print(f"FAIL {issue}")
    print(
        f"Python compatibility imports: {len(planned)} planned, {len(issues)} issue(s)"
    )
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
