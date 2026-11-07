"""Optional analyzer module that must stay unloaded during registry discovery."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alphus.contracts.cyclomatic import CyclomaticReport
from scripts.registry_spike.contracts import CheckProvider
from scripts.registry_spike.toy_policy import ToyPolicy


class ToyAnalyzer:
    def analyze(
        self, root: Path, files: Sequence[Path], settings: ToyPolicy
    ) -> CyclomaticReport:
        del root, files, settings
        return CyclomaticReport(
            metric="cyclomatic-complexity",
            outcome="clean",
            backends=(),
            functions=(),
            diagnostics=(),
        )


TOY_PROVIDER_CONTRACT: CheckProvider[ToyPolicy, CyclomaticReport] = ToyAnalyzer()
