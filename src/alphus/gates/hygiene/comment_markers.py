"""Find configured temporary-work markers in source comments."""

from __future__ import annotations

import io
import re
import tokenize
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.policy.sources import CommentMarkerPolicy
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_utf8_sig_text


class CommentLine(NamedTuple):
    line: int
    text: str


_RAW_STRING = re.compile(r'R"(?P<delimiter>[^\s()\\"]{0,16})\(')


def _python_comments(source: str) -> list[CommentLine]:
    return [
        CommentLine(token.start[0], token.string[1:])
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]


def _toml_comments(source: str) -> list[CommentLine]:
    """Read hash comments while respecting single and multiline strings."""
    comments: list[CommentLine] = []
    quote = ""
    index = 0
    line = 1
    while index < len(source):
        character = source[index]
        if quote:
            if source.startswith(quote, index):
                index += len(quote)
                quote = ""
                continue
            if character == "\\" and quote.startswith('"'):
                index += 2
                continue
            if character == "\n":
                line += 1
                if len(quote) == 1:
                    quote = ""
            index += 1
            continue
        if source.startswith('"""', index) or source.startswith("'''", index):
            quote = source[index : index + 3]
            index += 3
        elif character in {"'", '"'}:
            quote = character
            index += 1
        elif character == "#":
            end = source.find("\n", index)
            if end < 0:
                end = len(source)
            comments.append(CommentLine(line, source[index + 1 : end]))
            index = end
        else:
            if character == "\n":
                line += 1
            index += 1
    return comments


def _slash_comments(source: str) -> list[CommentLine]:
    """Read ordinary C-family comments outside strings and C++ raw strings."""
    comments: list[CommentLine] = []
    index = 0
    line = 1
    while index < len(source):
        raw = _RAW_STRING.match(source, index)
        if raw is not None:
            terminator = ")" + raw.group("delimiter") + '"'
            end = source.find(terminator, raw.end())
            if end >= 0:
                next_index = end + len(terminator)
                line += source.count("\n", index, next_index)
                index = next_index
                continue
        if source[index : index + 2] == "//":
            end = source.find("\n", index)
            if end < 0:
                end = len(source)
            comments.append(CommentLine(line, source[index + 2 : end]))
            index = end
            continue
        if source[index : index + 2] == "/*":
            end = source.find("*/", index + 2)
            if end < 0:
                end = len(source)
                next_index = end
            else:
                next_index = end + 2
            body = source[index + 2 : end]
            comments.extend(
                CommentLine(line + offset, part)
                for offset, part in enumerate(body.split("\n"))
            )
            line += source.count("\n", index, next_index)
            index = next_index
            continue
        character = source[index]
        if character in {"'", '"', "`"}:
            quote = character
            index += 1
            while index < len(source):
                character = source[index]
                if character == "\\":
                    index += 2
                    continue
                if character == "\n":
                    line += 1
                index += 1
                if character == quote:
                    break
            continue
        if character == "\n":
            line += 1
        index += 1
    return comments


def check_comment_markers(
    root: Path, paths: Iterable[Path], policy: CommentMarkerPolicy
) -> list[Finding]:
    """Report selected markers in supported source comment syntaxes."""
    checkout = root.resolve(strict=True)
    pattern = re.compile(
        r"(?<!\w)(?:"
        + "|".join(re.escape(item) for item in policy.markers)
        + r")(?!\w)",
        re.IGNORECASE,
    )
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = relative.as_posix()
        if relative.suffix.lower() not in policy.extensions or any(
            matches_path(name, excluded) for excluded in policy.exclude
        ):
            continue
        path = checkout / relative
        if path.is_symlink() or not path.is_file():
            continue
        if not path.resolve(strict=True).is_relative_to(checkout):
            continue
        source = read_utf8_sig_text(path)
        try:
            if relative.suffix.lower() in {".py", ".pyi"}:
                comments = _python_comments(source)
            elif relative.suffix.lower() == ".toml":
                comments = _toml_comments(source)
            else:
                comments = _slash_comments(source)
        except (tokenize.TokenError, IndentationError) as error:
            findings.append(
                Finding(
                    rule_id=rule_tag(
                        Scope.ANY,
                        Framework.NONE,
                        Category.HYGIENE,
                        "comment-scan-failed",
                    ),
                    path=name,
                    message=f"cannot scan Python comments: {error}",
                )
            )
            continue
        findings.extend(
            Finding(
                rule_id=rule_tag(
                    Scope.ANY, Framework.NONE, Category.HYGIENE, "comment-marker-found"
                ),
                path=name,
                line=line,
                message=f"temporary-work marker {match.group().upper()} in comment",
            )
            for line, comment in comments
            for match in pattern.finditer(comment)
        )
    return findings
