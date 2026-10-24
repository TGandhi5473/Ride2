from typing import Any
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from core import Config, QuotaExceededError
from .base_scraper import BaseScraper


class YouTubeScraper(BaseScraper):
    """Search videos and normalize the documented YouTube Data API v3 resources."""

    def __init__(self):
        super().__init__(platform="youtube")
        self.api_key = Config.YOUTUBE_API_KEY
        if not self.api_key:
            self.logger.warning("YouTube API key is not configured")
            self.is_active = False
            return
        try:
            self.youtube = build("youtube", "v3", developerKey=self.api_key, cache_discovery=False)
        except Exception as exc:
            self.logger.error("Could not initialize YouTube client (%s)", type(exc).__name__)
            self.is_active = False

    def fetch_trending(self, topic: str, limit: int = 10):
        """Search.list returns Video searchResult objects, not full Video resources."""
        try:
            response = self.youtube.search().list(
                q=topic,
                part="snippet",
                type="video",
                maxResults=max(1, min(limit, 50)),
                order="viewCount",
                fields=("items(id/videoId,snippet(title,description,channelId,channelTitle," 
                        "publishedAt,liveBroadcastContent,thumbnails))"),
            ).execute(num_retries=2)
            return response.get("items", [])
        except HttpError as exc:
            reason = str(getattr(exc, "error_details", "")).lower()
            message = str(exc).lower()
            quota_hit = exc.resp.status == 429 or (
                exc.resp.status == 403 and any(token in reason + message for token in
                    ("quota", "dailylimitexceeded", "quotaexceeded"))
            )
            if quota_hit:
                self.is_active = False
                self.logger.critical("YouTube quota exhausted or rate limited")
                raise QuotaExceededError("youtube") from exc
            raise

    def format_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        """Keep normalized columns used by dbt plus the original SearchResult fields.

        The Search API's `snippet` has video metadata but not statistics. We preserve
        its documented ID/snippet structure and do not invent view/like counts. The
        raw search result makes future model changes possible without re-fetching.
        """
        video_id = (item.get("id") or {}).get("videoId")
        snippet = item.get("snippet") or {}
        thumbnails = snippet.get("thumbnails") or {}
        # Legacy `thumbnails` remains for the current stg_yt model; new code can use
        # thumbnail_urls, channel_id, and the complete provider search result.
        return {
            "source_id": video_id,
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "channel": snippet.get("channelTitle"),
            "channel_id": snippet.get("channelId"),
            "published_at": snippet.get("publishedAt"),
            "live_broadcast_content": snippet.get("liveBroadcastContent"),
            "thumbnail_urls": {name: value.get("url") for name, value in thumbnails.items() if isinstance(value, dict) and value.get("url")},
            "thumbnails": (thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}).get("url"),
            "provider": "youtube_data_api_v3",
            "provider_resource": item,
        }
