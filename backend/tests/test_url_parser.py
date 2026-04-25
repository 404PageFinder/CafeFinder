import pytest

from app.services.url_parser import parse_url, UnsupportedURLError


class TestYouTubeURLs:
    def test_youtube_shorts(self):
        result = parse_url("https://www.youtube.com/shorts/abc123XYZ")
        assert result.platform == "youtube"
        assert result.content_type == "shorts"
        assert result.content_id == "abc123XYZ"
        assert result.normalized_url == "https://www.youtube.com/shorts/abc123XYZ"

    def test_youtube_shorts_no_www(self):
        result = parse_url("https://youtube.com/shorts/abc123XYZ")
        assert result.platform == "youtube"
        assert result.content_type == "shorts"

    def test_youtube_shorts_mobile(self):
        result = parse_url("https://m.youtube.com/shorts/abc123XYZ")
        assert result.platform == "youtube"
        assert result.content_type == "shorts"

    def test_youtube_watch(self):
        result = parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert result.platform == "youtube"
        assert result.content_type == "video"
        assert result.content_id == "dQw4w9WgXcQ"

    def test_youtube_watch_with_extra_params(self):
        result = parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s")
        assert result.content_id == "dQw4w9WgXcQ"

    def test_youtu_be_short(self):
        result = parse_url("https://youtu.be/dQw4w9WgXcQ")
        assert result.platform == "youtube"
        assert result.content_type == "video"
        assert result.content_id == "dQw4w9WgXcQ"


class TestRejectedURLs:
    def test_instagram_rejected_with_helpful_message(self):
        with pytest.raises(UnsupportedURLError, match="Phase 1"):
            parse_url("https://www.instagram.com/reel/xyz789/")

    def test_empty_url(self):
        with pytest.raises(UnsupportedURLError):
            parse_url("")

    def test_whitespace_only(self):
        with pytest.raises(UnsupportedURLError):
            parse_url("   ")

    def test_unknown_platform(self):
        with pytest.raises(UnsupportedURLError):
            parse_url("https://tiktok.com/@user/video/123")
