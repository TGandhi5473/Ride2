from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
import logging


class BaseScraper(ABC):
    """Shared fetch/format lifecycle; errors propagate so failed runs aren't mistaken for no results."""

    def __init__(self, platform: str):
        self.platform = platform
        self.is_active = True
        self.logger = logging.getLogger(f"{platform.capitalize()}Scraper")

    @abstractmethod
    def fetch_trending(self, topic: str, limit: int = 10) -> list[Any]:
        """Fetch raw provider results for a topic."""

    @abstractmethod
    def format_payload(self, raw_data: Any) -> dict[str, Any]:
        """Convert provider objects to JSON-compatible payloads."""

    def run(self, topic: str, limit: int = 10) -> list[dict[str, Any]]:
        if not self.is_active:
            self.logger.warning("Skipping inactive %s scraper", self.platform)
            return []
        self.logger.info("Fetching %s trend results for %r", self.platform, topic)
        results = self.fetch_trending(topic, limit=limit)
        now = datetime.now(timezone.utc)
        return [
            {
                "platform": self.platform,
                "target_topic": topic,
                "payload": self.format_payload(item),
                "ingested_at": now,
            }
            for item in (results or [])
        ]
