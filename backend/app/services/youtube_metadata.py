"""Fetch YouTube video metadata via the Data API v3."""

import re
import httpx
from dataclasses import dataclass, field

from app.config import settings

YT_API_URL = "https://www.googleapis.com/youtube/v3/videos"


@dataclass
class YouTubeMetadata:
    video_id: str
    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    channel_title: str = ""
    published_at: str = ""
    thumbnail_url: str = ""
    raw: dict = field(default_factory=dict)


class YouTubeFetchError(Exception):
    pass


async def fetch_youtube_metadata(video_id: str) -> YouTubeMetadata:
    params = {
        "part": "snippet",
        "id": video_id,
        "key": settings.youtube_api_key,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(YT_API_URL, params=params)
        if r.status_code != 200:
            raise YouTubeFetchError(f"YouTube API {r.status_code}: {r.text}")
        data = r.json()

    items = data.get("items") or []
    if not items:
        raise YouTubeFetchError(f"Video not found: {video_id}")

    snippet = items[0]["snippet"]
    thumbs = snippet.get("thumbnails", {})
    thumb_url = (
        (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("default") or {}).get("url", "")
    )

    desc = snippet.get("description", "") or ""
    hashtags_in_desc = re.findall(r"#(\w+)", desc)
    api_tags = list(snippet.get("tags") or [])
    # Combine API tags + hashtags scraped from description, dedupe while preserving order
    combined_tags = list(dict.fromkeys(api_tags + hashtags_in_desc))

    return YouTubeMetadata(
        video_id=video_id,
        title=snippet.get("title", "") or "",
        description=desc,
        tags=combined_tags,
        channel_title=snippet.get("channelTitle", "") or "",
        published_at=snippet.get("publishedAt", "") or "",
        thumbnail_url=thumb_url,
        raw=items[0],
    )
