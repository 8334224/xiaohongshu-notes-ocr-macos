from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from utils import AppError, clean_note_text
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
        self.assertIsNone(result.note_text)
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
        self.assertIsNone(result.note_text)
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
    def test_fetch_public_note_extracts_note_text_from_meta_description(self, mock_urlopen) -> None:
        html = """
        <html>
          <head>
            <meta property="og:title" content="公开笔记">
            <meta name="author" content="作者">
            <meta name="description" content="第一段\n\n第二段">
            <meta property="og:image" content="https://ci.xiaohongshu.com/cover.jpg">
          </head>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, self.parsed_url.canonical_url)

        result = fetch_public_note(self.parsed_url)

        self.assertEqual(result.note_text, "第一段\n\n第二段")

    def test_clean_note_text_removes_repeated_core_title_prefix(self) -> None:
        cleaned = clean_note_text(
            "孩子有自己的人生对孩子的过度的干预与越界，既是对孩子生命轨迹的冒犯。",
            "一念空山-回响：孩子有自己的人生",
        )

        self.assertEqual(cleaned, "对孩子的过度的干预与越界，既是对孩子生命轨迹的冒犯。")

    def test_clean_note_text_removes_tail_hashtag_block(self) -> None:
        cleaned = clean_note_text(
            "正文内容。 #亲子关系 #家庭教育 #孩子的命运",
            "标题",
        )

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_removes_tail_hashtags_after_sentence_punctuation(self) -> None:
        cleaned = clean_note_text(
            "正文内容。#金融 #信息差 #商业大佬思维",
            "标题",
        )

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_removes_tail_hashtags_without_newline(self) -> None:
        cleaned = clean_note_text(
            "正文内容 #金融 #信息差 #商业大佬思维",
            "标题",
        )

        self.assertEqual(cleaned, "正文内容")

    def test_clean_note_text_removes_tail_edit_metadata(self) -> None:
        cleaned = clean_note_text(
            "正文内容。 编辑于 18 小时前 浙江",
            "标题",
        )

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_removes_tail_month_day_location_metadata(self) -> None:
        cleaned = clean_note_text("正文内容。 03-08 北京", "标题")

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_removes_tail_short_month_day_location_metadata(self) -> None:
        cleaned = clean_note_text("正文内容。 3-8 北京", "标题")

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_removes_tail_full_date_location_metadata(self) -> None:
        cleaned = clean_note_text("正文内容。 2026-03-08 北京", "标题")

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_removes_tail_slash_date_location_metadata(self) -> None:
        cleaned = clean_note_text("正文内容。 03/08 北京", "标题")

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_removes_connected_tags_and_tail_metadata(self) -> None:
        cleaned = clean_note_text(
            "正文内容。 #亲子关系 #家庭教育 #尊重孩子的选择编辑于 18 小时前 浙江",
            "标题",
        )

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_removes_connected_tags_and_pure_date_location_metadata(self) -> None:
        cleaned = clean_note_text(
            "正文内容。#金融 #商业 03-08 北京",
            "标题",
        )

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_keeps_normal_body_text(self) -> None:
        cleaned = clean_note_text(
            "如果你在亲子关系家庭教育中焦虑迷茫，可以听阅我主页的内容。",
            "标题",
        )

        self.assertEqual(cleaned, "如果你在亲子关系家庭教育中焦虑迷茫，可以听阅我主页的内容。")

    def test_clean_note_text_keeps_middle_date_in_normal_body(self) -> None:
        cleaned = clean_note_text(
            "这篇文章在 03-08 北京开会后形成，后面还有正式分析内容。",
            "标题",
        )

        self.assertEqual(cleaned, "这篇文章在 03-08 北京开会后形成，后面还有正式分析内容。")

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_raises_on_network_failure(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = OSError("network down")

        with self.assertRaisesRegex(AppError, "公开页面抓取失败"):
            fetch_public_note(self.parsed_url)
