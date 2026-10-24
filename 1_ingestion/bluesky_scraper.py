from typing import Any
from atproto import Client
from core import Config, ProviderAuthenticationError
from .base_scraper import BaseScraper


class BlueskyScraper(BaseScraper):
    """Search public Bluesky posts and retain AT Protocol record context."""

    def __init__(self):
        super().__init__(platform="bluesky")
        self.client = Client()
        self.handle = Config.BSKY_HANDLE
        self.password = Config.BSKY_PASSWORD
        if not self.handle or not self.password:
            self.is_active = False
            self.logger.info("Bluesky credentials not configured; scraper disabled")
            return
        try:
            self.client.login(self.handle, self.password)
        except Exception as exc:
            self.is_active = False
            # Provider exceptions can contain request context or credential-adjacent
            # details; expose only a generic message to callers/logging.
            raise ProviderAuthenticationError("Bluesky login failed; verify handle and app password") from exc

    def fetch_trending(self, topic: str, limit: int = 10):
        """The app.bsky.feed.searchPosts XRPC returns a feed of hydrated post views."""
        response = self.client.app.bsky.feed.search_posts(params={
            "q": topic,
            "limit": max(1, min(limit, 100)),
        })
        return response.posts or []

    @staticmethod
    def _get(obj: Any, key: str, default=None):
        """Read generated AT Protocol model attributes and JSON aliases."""
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            # The protocol JSON schema uses camelCase; Python clients commonly
            # expose snake_case model fields.
            camel = key.split("_")[0] + "".join(part.title() for part in key.split("_")[1:])
            return obj.get(camel, default)
        return getattr(obj, key, default)

    @classmethod
    def _plain(cls, value: Any):
        """Convert generated AT Protocol models recursively to JSON-compatible data."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): cls._plain(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._plain(item) for item in value]
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return cls._plain(model_dump(by_alias=True, exclude_none=True))
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return cls._plain(to_dict())
        if hasattr(value, "__dict__"):
            return {key: cls._plain(item) for key, item in vars(value).items() if not key.startswith("_")}
        return str(value)

    def format_payload(self, feed_view: Any) -> dict[str, Any]:
        """Normalize hydrated PostView fields and preserve source record context.

        Search results hold the post under `post`; counts belong to the outer feed
        view. Preserve provider_resource for fields that this app doesn't model yet.
        """
        post = self._get(feed_view, "post", feed_view)
        record = self._get(post, "record", {})
        author = self._get(post, "author", {})
        uri = self._get(post, "uri")
        created_at = self._get(record, "created_at") or self._get(record, "createdAt")
        return {
            "source_id": uri,
            "uri": uri,
            "cid": self._get(post, "cid"),
            "text": self._get(record, "text"),
            "author": self._get(author, "handle"),
            "author_did": self._get(author, "did"),
            "created_at": created_at,
            "indexed_at": self._get(post, "indexed_at") or self._get(post, "indexedAt"),
            "like_count": self._get(feed_view, "like_count", 0) or 0,
            "reply_count": self._get(feed_view, "reply_count", 0) or 0,
            "repost_count": self._get(feed_view, "repost_count", 0) or 0,
            "quote_count": self._get(feed_view, "quote_count", 0) or 0,
            "bookmark_count": self._get(feed_view, "bookmark_count", 0) or 0,
            "langs": self._get(record, "langs", []) or [],
            "labels": self._plain(self._get(post, "labels", []) or []),
            "embed": self._plain(self._get(post, "embed")),
            "record": self._plain(record),
            "provider": "atproto_app_bsky_feed_searchPosts",
            "provider_resource": self._plain(feed_view),
        }
