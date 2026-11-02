"""Types at the isolated Lizard API worker boundary."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr


class LizardFunctionInfo(Protocol):
    """Fields consumed from a Lizard native function record."""

    name: str
    long_name: str
    start_line: int
    cyclomatic_complexity: int


class LizardFileInfo(Protocol):
    """Fields consumed from a Lizard native file record."""

    filename: str
    function_list: Sequence[LizardFunctionInfo | None]


class LizardApi(Protocol):
    """Narrow portion of Lizard's public analysis API used by Alphus."""

    def get_extensions(self, names: Sequence[str]) -> Sequence[object]: ...

    def analyze_files(
        self, files: Sequence[str], *, exts: Sequence[object]
    ) -> Iterable[LizardFileInfo | None]: ...


class LizardFunctionRecord(BaseModel):
    """Validated function data serialized from the worker process."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: StrictStr
    line: StrictInt
    value: StrictInt


class LizardWorkerRequest(BaseModel):
    """Bounded command-independent input manifest sent to the worker on stdin."""

    model_config = ConfigDict(extra="forbid", strict=True)

    files: tuple[StrictStr, ...]


class LizardFileRecord(BaseModel):
    """Validated per-file records serialized from the worker process."""

    model_config = ConfigDict(extra="forbid", strict=True)

    path: StrictStr
    functions: tuple[LizardFunctionRecord, ...]


class LizardWorkerResponse(BaseModel):
    """Success or failure response on the worker's single-JSON stdout protocol."""

    model_config = ConfigDict(extra="forbid", strict=True)

    version: StrictStr | None = None
    analyzed_file_count: StrictInt | None = None
    files: tuple[LizardFileRecord, ...] | None = None
    error: StrictStr | None = None
