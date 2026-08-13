"""Typed fatal integrity failures that must not degrade into partial research."""

from __future__ import annotations


class ResearchIntegrityError(RuntimeError):
    """A stable public reason for withholding substantive research output."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)

