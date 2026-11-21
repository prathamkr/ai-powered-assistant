"""Shared adapter interface. Status values: done | handed_off | failed | denied | unsupported."""
from dataclasses import dataclass


@dataclass
class Result:
    status: str
    detail: str = ""


class Adapter:
    name = "base"

    def capability_check(self) -> bool:
        return False

    def permission_check(self) -> str:  # granted | denied | not_required
        return "denied"

    def validate(self, payload) -> list:  # list of error strings
        return ["not implemented"]

    def preview(self, payload) -> str:
        return ""

    def execute(self, payload) -> Result:
        return Result("unsupported", "adapter not implemented")


class UnsupportedAdapter(Adapter):
    """Placeholder for adapters not built yet. Never reports success."""

    def __init__(self, name):
        self.name = name
