from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from utils import AppError
from xhs_public_fetcher import PublicFetchResult, XhsPublicFetcher, fetch_public_note
from xhs_url_validator import ParsedXhsUrl


class _FakeHeaders:
    def __init__(self, charset: str = "utf-8") -> None:
        self.charset = charset

    def get_content_charset(self):
        return self.charset


class _FakeResponse:
    def __init__(self, html: str, final_url: str) -> None:
        self._html = html.encode("utf-8")
        self._final_url = final_url
        self.headers = _FakeHeaders()

    def read(self) -> bytes:
        return self._html

    def geturl(self) -> str:
        return self._final_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class PublicFetcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parsed_url = ParsedXhsUrl(
            original_input="https://www.xiaohongshu.com/explore/699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like",
            extracted_url="https://www.xiaohongshu.com/explore/699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like",
            resolved_url="https://www.xiaohongshu.com/explore/699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like",
            canonical_url="https://www.xiaohongshu.com/explore/699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like",
            note_id="699be056000000000c0349ff",
            xsec_token="abc",
            xsec_source="pc_like",
            share_link_host=None,
        )

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_prefers_script_embedded_images(self, mock_urlopen) -> None:
        html = """
        <html>
          <head>
            <meta property="og:title" content="公开笔记标题 - 小红书">
            <meta name="author" content="公开作者">
            <script>
              window.__INITIAL_STATE__ = {
                "note": {
                  "images": [
                    "https://ci.xiaohongshu.com/body1.jpg?imageView2/2/w/1080",
                    "https://ci.xiaohongshu.com/body2.jpg",
                    "https://ci.xiaohongshu.com/body1.jpg!large"
                  ]
                }
              };
            </script>
            <meta property="og:image" content="https://ci.xiaohongshu.com/cover.jpg">
          </head>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, self.parsed_url.canonical_url)

        result = fetch_public_note(self.parsed_url)

        self.assertIsInstance(result, PublicFetchResult)
        self.assertEqual(result.final_url, self.parsed_url.canonical_url)
        self.assertEqual(
            result.image_urls,
            [
                "https://ci.xiaohongshu.com/body1.jpg?imageView2/2/w/1080",
                "https://ci.xiaohongshu.com/body2.jpg",
            ],
        )
        self.assertEqual(result.title, "公开笔记标题")
        self.assertEqual(result.author, "公开作者")
        self.assertEqual(result.extraction_method, "embedded_json")
        self.assertIsNone(result.html_path)

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_falls_back_to_meta_images(self, mock_urlopen) -> None:
        html = """
        <html>
          <head>
            <meta property="og:title" content="公开笔记">
            <meta property="og:image" content="https://ci.xiaohongshu.com/cover1.jpg">
            <meta name="twitter:image" content="https://ci.xiaohongshu.com/cover2.jpg">
          </head>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, "https://www.xiaohongshu.com/explore/final123")

        result = XhsPublicFetcher().fetch(self.parsed_url)

        self.assertEqual(result.final_url, "https://www.xiaohongshu.com/explore/final123")
        self.assertEqual(
            result.image_urls,
            [
                "https://ci.xiaohongshu.com/cover1.jpg",
                "https://ci.xiaohongshu.com/cover2.jpg",
            ],
        )
        self.assertEqual(result.extraction_method, "meta_tags")

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_can_save_html_to_path(self, mock_urlopen) -> None:
        html = """
        <html>
          <head><title>公开标题 - 小红书</title></head>
          <body>https://ci.xiaohongshu.com/body1.jpg</body>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, self.parsed_url.canonical_url)

        with TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "debug" / "public_note.html"

            result = fetch_public_note(self.parsed_url, html_output_path=html_path)

            self.assertEqual(result.html_path, str(html_path))
            self.assertTrue(html_path.exists())
            self.assertIn("body1.jpg", html_path.read_text(encoding="utf-8"))

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_extracts_author_from_embedded_json_when_meta_missing(self, mock_urlopen) -> None:
        html = """
        <html>
          <head>
            <title>公开标题 - 小红书</title>
            <script>
              {"note":{"nickname":"测试作者","images":["https://ci.xiaohongshu.com/body1.jpg"]}}
            </script>
          </head>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, self.parsed_url.canonical_url)

        result = fetch_public_note(self.parsed_url)

        self.assertEqual(result.author, "测试作者")
        self.assertEqual(result.image_urls, ["https://ci.xiaohongshu.com/body1.jpg"])

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_raises_on_network_failure(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = OSError("network down")

        with self.assertRaisesRegex(AppError, "公开页面抓取失败"):
            fetch_public_note(self.parsed_url)
