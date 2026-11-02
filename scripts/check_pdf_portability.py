"""Check PDF link actions against a declared offline delivery contract."""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Sequence
from pathlib import Path, PureWindowsPath
from typing import Literal, Protocol, cast
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["self_contained", "bundle"]
    bundle_root: Path | None = None
    allowed_uri_schemes: tuple[str, ...] = ("https", "http", "mailto")


class _Dictionary(Protocol):
    def get(self, key: str, default: object = None) -> object: ...


class _Page(Protocol):
    @property
    def annotations(self) -> Sequence[object] | None: ...


class _Reader(Protocol):
    pages: Sequence[_Page]


class _ReaderFactory(Protocol):
    def __call__(self, pdf_path: Path, strict: bool = True) -> _Reader: ...


class _PdfApi(Protocol):
    PdfReader: _ReaderFactory


def _dictionary(value: object) -> _Dictionary:
    getter = getattr(value, "get_object", None)
    resolved = getter() if callable(getter) else value
    return cast(_Dictionary, resolved)


def _local_path(value: str) -> bool:
    path = unquote(value)
    parsed = urlsplit(path)
    return (
        PureWindowsPath(path).is_absolute()
        or path.startswith(("//", "\\\\"))
        or Path(path).is_absolute()
        or parsed.scheme.casefold() == "file"
    )


def _bundle_target(root: Path, value: str) -> tuple[bool, str]:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return False, "relative companion target must not contain a URI scheme or host"
    relative = Path(unquote(parsed.path))
    if relative.is_absolute():
        return False, "absolute local path is outside the declared bundle contract"
    resolved_root = root.resolve()
    target = (resolved_root / relative).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError:
        return False, "companion target escapes the declared bundle root"
    if not target.is_file():
        return False, "declared bundle companion is missing"
    return True, ""


def validate_portability(
    pdf_path: Path, contract_path: Path
) -> tuple[list[str], list[str]]:
    """Return policy violations and unsupported/unknown action evidence."""
    contract = _Contract.model_validate_json(contract_path.read_text(encoding="utf-8"))
    if contract.mode not in {"self_contained", "bundle"}:
        raise ValueError("mode must be 'self_contained' or 'bundle'")
    if contract.mode == "bundle" and contract.bundle_root is None:
        raise ValueError("bundle mode requires bundle_root")
    if contract.mode == "self_contained" and contract.bundle_root is not None:
        raise ValueError("bundle_root is only valid in bundle mode")

    try:
        api = cast(_PdfApi, importlib.import_module("pypdf"))
    except ImportError as error:
        raise RuntimeError(
            "install the optional PDF extra: pip install 'alphus[pdf]'"
        ) from error
    try:
        reader = api.PdfReader(pdf_path, strict=True)
    except Exception as error:
        raise RuntimeError(f"cannot parse PDF actions: {error}") from error

    allowed = {scheme.casefold() for scheme in contract.allowed_uri_schemes}
    failures: list[str] = []
    unknown: list[str] = []
    root = contract.bundle_root
    for page_number, page in enumerate(reader.pages, start=1):
        annotations = page.annotations
        if annotations is None:
            continue
        for index, item in enumerate(annotations, start=1):
            annotation = _dictionary(item)
            if str(annotation.get("/Subtype")) != "/Link":
                continue
            action_value = annotation.get("/A")
            if action_value is None:
                if annotation.get("/Dest") is not None:
                    continue
                unknown.append(
                    f"page {page_number} link {index}: no destination or action"
                )
                continue
            try:
                action = _dictionary(action_value)
                kind = str(action.get("/S"))
            except Exception as error:  # noqa: BLE001 - malformed PDF objects are unknown evidence
                unknown.append(
                    f"page {page_number} link {index}: malformed action ({error})"
                )
                continue
            prefix = f"page {page_number} link {index} {kind}"
            if kind == "/GoTo":
                continue
            if kind == "/URI":
                uri_value = action.get("/URI")
                if not isinstance(uri_value, str):
                    unknown.append(f"{prefix}: malformed URI action")
                    continue
                uri = str(uri_value)
                parsed = urlsplit(uri)
                scheme = parsed.scheme.casefold()
                if scheme == "file" or _local_path(uri):
                    failures.append(
                        f"{prefix}: local filesystem URI/path violates delivery policy"
                    )
                elif not parsed.path and parsed.fragment:
                    continue
                elif not scheme:
                    if contract.mode == "self_contained":
                        failures.append(
                            f"{prefix}: relative companion is unavailable in self-contained PDF"
                        )
                    elif root is not None:
                        ok, reason = _bundle_target(root, uri)
                        if not ok:
                            failures.append(f"{prefix}: {reason}")
                elif scheme not in allowed:
                    failures.append(
                        f"{prefix}: URI scheme {scheme!r} is not allowed by contract"
                    )
                continue
            if kind == "/GoToR":
                file_spec = action.get("/F")
                if isinstance(file_spec, str):
                    target = str(file_spec)
                else:
                    try:
                        file_dictionary = _dictionary(file_spec)
                        target_value = file_dictionary.get(
                            "/UF", file_dictionary.get("/F")
                        )
                        target = str(target_value) if target_value is not None else ""
                    except Exception:  # noqa: BLE001 - unsupported file specifier
                        target = ""
                if not target:
                    unknown.append(
                        f"{prefix}: remote document target is missing or unsupported"
                    )
                elif _local_path(target):
                    failures.append(
                        f"{prefix}: remote GoTo uses an absolute local target"
                    )
                elif contract.mode == "self_contained":
                    failures.append(
                        f"{prefix}: remote-document GoTo is unavailable in self-contained PDF"
                    )
                elif root is not None:
                    ok, reason = _bundle_target(root, target)
                    if not ok:
                        failures.append(f"{prefix}: {reason}")
                continue
            if kind == "/Launch":
                failures.append(
                    f"{prefix}: launch/file actions violate delivery policy"
                )
                continue
            unknown.append(
                f"{prefix}: unsupported action kind; not executed or fetched"
            )
    return failures, unknown


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("contract", type=Path)
    args = parser.parse_args(argv)
    try:
        failures, unknown = validate_portability(args.pdf, args.contract)
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(f"UNKNOWN: {error}", file=sys.stderr)
        return 2
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    for note in unknown:
        print(f"UNKNOWN: {note}", file=sys.stderr)
    if failures:
        return 1
    if unknown:
        return 2
    print("PDF link actions satisfy the declared offline delivery contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
