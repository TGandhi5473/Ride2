"""Lazy factory keeps dashboard-only imports independent of scraping packages."""


class ScraperFactory:
    _SCRAPERS = {
        "youtube": ("ingestion.youtube_scraper", "YouTubeScraper"),
        "bluesky": ("ingestion.bluesky_scraper", "BlueskyScraper"),
    }

    @classmethod
    def get_scraper(cls, platform: str):
        from importlib import import_module
        from . import _ingestion_dir

        key = platform.lower()
        if key not in cls._SCRAPERS:
            raise ValueError(f"Platform '{platform}' is not supported.")
        module_name, class_name = cls._SCRAPERS[key]
        module = import_module(module_name)
        return getattr(module, class_name)()
