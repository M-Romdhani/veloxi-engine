"""HTML scraper adapter — scaffold. Configure selectors + implement parsing."""
from __future__ import annotations

from ..models import SourceType
from .base import AdapterRegistry, SourceAdapter


@AdapterRegistry.register
class HtmlScraperAdapter(SourceAdapter):
    type = SourceType.scraper.value

    def fetch(self):
        # Scaffold: wire a real parser per target site (e.g. selectolax/lxml)
        # driven by config.item_selector / title_selector / url_selector.
        raise NotImplementedError(
            "Scraper adapter is a scaffold. Provide config.item_selector, "
            "title_selector and url_selector, then implement parsing for the "
            "target site before enabling this source."
        )
