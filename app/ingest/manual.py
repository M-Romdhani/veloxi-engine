"""Manual adapter — items arrive via the admin route, not by pulling."""
from __future__ import annotations

from ..models import SourceType
from .base import AdapterRegistry, SourceAdapter


@AdapterRegistry.register
class ManualAdapter(SourceAdapter):
    type = SourceType.manual.value

    def fetch(self):
        # Manual opportunities are submitted through POST /admin/opportunities,
        # which stages a RawOpportunity directly. Nothing to pull here.
        return []
