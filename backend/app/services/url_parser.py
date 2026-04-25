"""URL parser for YouTube links.

Phase 1 supports:
- youtube.com/watch?v={id}
- youtu.be/{id}
- youtube.com/shorts/{id}
- m.youtube.com / www.youtube.com variants

Instagram / other platforms are deliberately rejected at this stage.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs


@dataclass
class ParsedURL:
    platform: str          # "youtube" | "instagram" | "unknown"
    content_type: str      # "video" | "shorts" | "reel" | "post" | "unknown"
    content_id: str
    normalized_url: str


class UnsupportedURLError(ValueError):
    pass


_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")
_YT_SHORTS_RE = re.compile(r"/shorts/([A-Za-z0-9_-]{6,})")
_YT_SHORT_HOST_RE = re.compile(r"/([A-Za-z0-9_-]{6,})")


def parse_url(raw_url: str) -> ParsedURL:
    if not raw_url or not raw_url.strip():
        raise UnsupportedURLError("Empty URL")

    url = raw_url.strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")

    # YouTube Shorts: youtube.com/shorts/{id}
    if host.endswith("youtube.com"):
        m = _YT_SHORTS_RE.search(parsed.path)
        if m:
            vid = m.group(1)
            return ParsedURL(
                platform="youtube",
                content_type="shorts",
                content_id=vid,
                normalized_url=f"https://www.youtube.com/shorts/{vid}",
            )

        # Standard watch: youtube.com/watch?v={id}
        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            vid = (qs.get("v") or [None])[0]
            if vid and _VIDEO_ID_RE.match(vid):
                return ParsedURL(
                    platform="youtube",
                    content_type="video",
                    content_id=vid,
                    normalized_url=f"https://www.youtube.com/watch?v={vid}",
                )

    # Shortened: youtu.be/{id}
    if host == "youtu.be":
        m = _YT_SHORT_HOST_RE.search(parsed.path)
        if m:
            vid = m.group(1)
            return ParsedURL(
                platform="youtube",
                content_type="video",
                content_id=vid,
                normalized_url=f"https://www.youtube.com/watch?v={vid}",
            )

    # Instagram detection — recognized but not supported in Phase 1
    if host.endswith("instagram.com"):
        raise UnsupportedURLError(
            "Instagram is not supported in Phase 1 MVP. Please use a YouTube link."
        )

    raise UnsupportedURLError(f"Unsupported URL: {raw_url}")
