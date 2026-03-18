from __future__ import annotations

from app.inkypi_adapter import InkyPiAdapter
from app.models import DisplayRequest, DisplayResult


class DisplayService:
    def __init__(self, adapter: InkyPiAdapter):
        self.adapter = adapter

    def display(self, request: DisplayRequest) -> DisplayResult:
        return self.adapter.display(request)

    def refresh_current(self) -> DisplayResult:
        return self.adapter.refresh_only()
