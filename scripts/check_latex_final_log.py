"""Check the final LaTeX log for unresolved references and expected output."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

_OUTPUT = re.compile(r"^Output written on\s+([^\s(]+)\s+\(", re.MULTILINE)
_PDFTEX_DESTINATION_START = re.compile(
    r"^[ \t]*pdfTeX warning \([^\)\r\n]{1,32}\):[ \t]+"
    r"destination with the same identifier"
    r"(?:[ \t]*\r?\n[ \t]*|[ \t]+)\(name\{",
    re.IGNORECASE | re.MULTILINE,
)
_PDFTEX_DESTINATION_SUFFIX = re.compile(
    r"\)\s*has\s*been\s*already\s*used,\s*duplicate\s*ignored\b",
    re.IGNORECASE,
)
_MAX_DESTINATION_ID_CHARS = 4096
_MAX_DESTINATION_SUFFIX_CHARS = 512
_UNRESOLVED = (
    re.compile(r"LaTeX Warning: Reference .+ undefined", re.IGNORECASE),
    re.compile(r"LaTeX Warning: Citation .+ undefined", re.IGNORECASE),
    re.compile(r"There were undefined references", re.IGNORECASE),
    re.compile(r"There were undefined citations", re.IGNORECASE),
    re.compile(r"Rerun to get cross-references right", re.IGNORECASE),
    re.compile(r"Rerun to get citations right", re.IGNORECASE),
    re.compile(r"Label\(s\) may have changed\. Rerun", re.IGNORECASE),
    re.compile(r"LaTeX Warning: Label .+ multiply defined", re.IGNORECASE),
)


def _pdftex_destination_issues(log: str) -> list[str]:
    issues: list[str] = []
    for start in _PDFTEX_DESTINATION_START.finditer(log):
        identifier_end = log.find(
            "}", start.end(), start.end() + _MAX_DESTINATION_ID_CHARS + 1
        )
        if identifier_end < 0:
            issues.append(
                "pdfTeX duplicate-destination identifier is unclosed or exceeds "
                f"the {_MAX_DESTINATION_ID_CHARS}-character scan bound; manual review required"
            )
            continue
        suffix_start = identifier_end + 1
        suffix = log[suffix_start : suffix_start + _MAX_DESTINATION_SUFFIX_CHARS]
        suffix = re.sub(r"\r?\n[ \t]*", "", suffix)
        if _PDFTEX_DESTINATION_SUFFIX.match(suffix):
            issues.append(
                "unresolved LaTeX cross-reference evidence: pdfTeX duplicate destination"
            )
    return issues


def validate_final_log(log_path: Path, pdf_path: Path) -> list[str]:
    """Return explicit log issues; caller must run the build immediately before."""
    try:
        log = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return [f"cannot read final LaTeX log {log_path}: {error}"]
    if not pdf_path.is_file():
        return [f"expected PDF output is missing: {pdf_path}"]
    reported = _OUTPUT.findall(log)
    if not reported:
        return ["log contains no 'Output written on' record; build identity is unknown"]
    if Path(reported[-1]).name != pdf_path.name:
        return [f"log reports output {reported[-1]!r}, expected {pdf_path.name!r}"]
    issues = [
        f"unresolved LaTeX cross-reference evidence: {pattern.pattern}"
        for pattern in _UNRESOLVED
        if pattern.search(log)
    ]
    issues.extend(_pdftex_destination_issues(log))
    return issues


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args(argv)
    issues = validate_final_log(args.log, args.pdf)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    print(
        f"LaTeX final log references {args.pdf}; no supported unresolved-reference warning found"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
