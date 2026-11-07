"""Strict settings for the registry architecture spike's toy check."""

from __future__ import annotations

from alphus.contracts.model import StrictModel


class ToyPolicy(StrictModel):
    marker: str
