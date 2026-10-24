"""Private command-line entry point for one isolated quality work unit."""

from __future__ import annotations

import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from alphus.execution._worker import dispatch_worker_request
from alphus.execution.worker_protocol import ErrorWorkerResponse, WorkerRequest


def main() -> int:
    """Reserve stdout for one response, including worker failures."""
    captured_output = StringIO()
    captured_error = StringIO()
    try:
        request = WorkerRequest.model_validate_json(sys.stdin.read())
        with redirect_stdout(captured_output), redirect_stderr(captured_error):
            response = dispatch_worker_request(request)
        if captured_output.getvalue() or captured_error.getvalue():
            raise ValueError("worker emitted unexpected output")
    except Exception as error:  # noqa: BLE001 - protocol reports worker failures.
        response = ErrorWorkerResponse(error=f"{type(error).__name__}: {error}")
    sys.stdout.write(response.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
