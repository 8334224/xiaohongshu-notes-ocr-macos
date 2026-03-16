from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from utils import AppError, clean_note_text, normalize_note_title, strip_redundant_leading_title
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
        self.assertEqual(result.note_type, "image")
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
        self.assertEqual(result.note_type, "image")
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
    def test_fetch_public_note_extracts_author_from_profile_link_html_for_explore_url(self, mock_urlopen) -> None:
        html = """
        <html>
          <head><title>公开标题 - 小红书</title></head>
          <body>
            <a href="/user/profile/5d3f838900000000120033a4">北海阿斯汤加瑜伽</a>
            <img src="https://ci.xiaohongshu.com/body1.jpg">
          </body>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, self.parsed_url.canonical_url)

        result = fetch_public_note(self.parsed_url)

        self.assertEqual(result.author, "北海阿斯汤加瑜伽")

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_extracts_author_from_profile_link_html_for_profile_url(self, mock_urlopen) -> None:
        profile_parsed_url = ParsedXhsUrl(
            original_input=(
                "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
                "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"
            ),
            extracted_url=(
                "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
                "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"
            ),
            resolved_url=(
                "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
                "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"
            ),
            canonical_url="https://www.xiaohongshu.com/explore/699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like",
            note_id="699be056000000000c0349ff",
            xsec_token="abc",
            xsec_source="pc_like",
            share_link_host=None,
        )
        html = """
        <html>
          <head><title>公开标题 - 小红书</title></head>
          <body>
            <a href="/user/profile/5d3f838900000000120033a4">北海阿斯汤加瑜伽</a>
            <img src="https://ci.xiaohongshu.com/body1.jpg">
          </body>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, profile_parsed_url.canonical_url)

        result = fetch_public_note(profile_parsed_url)

        self.assertEqual(result.author, "北海阿斯汤加瑜伽")

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

    def test_unescape_text_decodes_nested_quote_entities(self) -> None:
        raw = "作用力：为什么我们开始需要&amp;quot;搭子&amp;quot;了？"

        normalized = XhsPublicFetcher._unescape_text(raw)

        self.assertEqual(normalized, '作用力：为什么我们开始需要"搭子"了？')

    def test_normalize_note_title_decodes_nested_quote_entities(self) -> None:
        normalized = normalize_note_title("作用力：为什么我们开始需要&amp;quot;搭子&amp;quot;了？", "作者")

        self.assertEqual(normalized, '作用力：为什么我们开始需要"搭子"了？')

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_decodes_html_entities_in_author_title_and_text(self, mock_urlopen) -> None:
        html = """
        <html>
          <head>
            <meta property="og:title" content="作用力：为什么我们开始需要&amp;quot;搭子&amp;quot;了？ - 小红书">
            <meta name="author" content="Tom &amp;amp; Jerry">
            <meta name="description" content="我们开始需要&amp;quot;搭子&amp;quot;，因为陪伴很重要。">
            <meta property="og:image" content="https://ci.xiaohongshu.com/cover.jpg">
          </head>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, self.parsed_url.canonical_url)

        result = fetch_public_note(self.parsed_url)

        self.assertEqual(result.title, '作用力：为什么我们开始需要"搭子"了？')
        self.assertEqual(result.author, "Tom & Jerry")
        self.assertEqual(result.note_text, '我们开始需要"搭子"，因为陪伴很重要。')

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_detects_video_for_explore_url(self, mock_urlopen) -> None:
        html = """
        <html>
          <head>
            <meta property="og:title" content="视频笔记">
            <meta name="author" content="Cherry小圆圆呦">
            <meta name="description" content="视频正文">
          </head>
          <body>
            <video src="https://video.example.com/demo.mp4"></video>
          </body>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, self.parsed_url.canonical_url)

        result = fetch_public_note(self.parsed_url)

        self.assertEqual(result.note_type, "video")
        self.assertEqual(result.note_text, "视频正文")

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_detects_video_for_profile_url(self, mock_urlopen) -> None:
        profile_parsed_url = ParsedXhsUrl(
            original_input=(
                "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
                "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"
            ),
            extracted_url=(
                "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
                "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"
            ),
            resolved_url=(
                "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
                "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"
            ),
            canonical_url="https://www.xiaohongshu.com/explore/699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like",
            note_id="699be056000000000c0349ff",
            xsec_token="abc",
            xsec_source="pc_like",
            share_link_host=None,
        )
        html = """
        <html>
          <head>
            <meta property="og:title" content="视频笔记">
            <meta name="author" content="北海阿斯汤加瑜伽">
            <meta name="description" content="视频正文">
          </head>
          <body>
            <script>{"videoInfo":{"masterUrl":"https://video.example.com/demo.mp4"}}</script>
          </body>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, profile_parsed_url.canonical_url)

        result = fetch_public_note(profile_parsed_url)

        self.assertEqual(result.note_type, "video")

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_detects_video_from_og_type_and_og_video(self, mock_urlopen) -> None:
        html = """
        <html>
          <head>
            <meta property="og:type" content="video">
            <meta property="og:video" content="https://video.example.com/demo.mp4">
            <meta property="og:title" content="为什么我们开始需要&amp;quot;搭子&amp;quot;了？ - 小红书">
            <meta name="author" content="作用力">
            <meta property="og:image" content="https://sns-webpic-qc.xhscdn.com/cover!nd_dft_wlteh_jpg_3">
          </head>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, self.parsed_url.canonical_url)

        result = fetch_public_note(self.parsed_url)

        self.assertEqual(result.note_type, "video")
        self.assertEqual(result.title, '为什么我们开始需要"搭子"了？')
        self.assertEqual(result.author, "作用力")

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_keeps_video_when_only_single_cover_image_exists(self, mock_urlopen) -> None:
        html = """
        <html>
          <head>
            <meta property="og:title" content="1️⃣ 未来5年，最值钱的不是流量，是“慢内容”">
            <meta name="author" content="鑫瑶-高客单IP陪跑">
            <meta name="description" content="#天津小红书运营 #个人ip #获客">
            <meta property="og:image" content="https://sns-webpic-qc.xhscdn.com/cover!nd_dft_wlteh_webp_3">
            <script>{"videoInfo":{"masterUrl":"https://video.example.com/demo.mp4","videoId":"123"}}</script>
          </head>
          <body>
            <span>03-07 天津</span>
          </body>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, self.parsed_url.canonical_url)

        result = fetch_public_note(self.parsed_url)

        self.assertEqual(result.note_type, "video")
        self.assertEqual(len(result.image_urls), 1)

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_keeps_video_when_single_cover_and_false_pager_exist(self, mock_urlopen) -> None:
        html = """
        <html>
          <head>
            <meta property="og:title" content="1️⃣ 未来5年，最值钱的不是流量，是“慢内容”">
            <meta name="author" content="鑫瑶-高客单IP陪跑">
            <meta property="og:image" content="https://sns-webpic-qc.xhscdn.com/cover!nd_dft_wlteh_webp_3">
            <script>{"videoInfo":{"masterUrl":"https://video.example.com/demo.mp4","videoId":"123"}}</script>
          </head>
          <body>
            <span>1/3</span><span>03-07 天津</span>
          </body>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, self.parsed_url.canonical_url)

        result = fetch_public_note(self.parsed_url)

        self.assertEqual(result.note_type, "video")

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_prefers_image_when_gallery_pager_exists(self, mock_urlopen) -> None:
        html = """
        <html>
          <head>
            <meta property="og:title" content="扣子（Coze）和OpenClaw（龙虾）到底什么关">
            <meta name="author" content="老九的PPT">
            <script>{"videoInfo":{"masterUrl":"https://video.example.com/demo.mp4"}}</script>
            <script>{"note":{"images":["https://ci.xiaohongshu.com/body1.jpg","https://ci.xiaohongshu.com/body2.jpg"]}}</script>
          </head>
          <body>
            <div class="swiper">1/13</div>
          </body>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, self.parsed_url.canonical_url)

        result = fetch_public_note(self.parsed_url)

        self.assertEqual(result.note_type, "image")
        self.assertEqual(len(result.image_urls), 2)

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_prefers_image_when_profile_url_has_gallery_and_weak_video_signal(self, mock_urlopen) -> None:
        profile_parsed_url = ParsedXhsUrl(
            original_input=(
                "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
                "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"
            ),
            extracted_url=(
                "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
                "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"
            ),
            resolved_url=(
                "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
                "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"
            ),
            canonical_url="https://www.xiaohongshu.com/explore/699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like",
            note_id="699be056000000000c0349ff",
            xsec_token="abc",
            xsec_source="pc_like",
            share_link_host=None,
        )
        html = """
        <html>
          <head>
            <meta property="og:title" content="多图图文">
            <meta name="author" content="老九的PPT">
            <script>{"videoUrl":"https://video.example.com/noise.mp4"}</script>
          </head>
          <body>
            <div class="swiper-slide"><img src="https://ci.xiaohongshu.com/body1.jpg"></div>
            <div class="swiper-slide"><img src="https://ci.xiaohongshu.com/body2.jpg"></div>
            <span>1/13</span>
          </body>
        </html>
        """
        mock_urlopen.return_value = _FakeResponse(html, profile_parsed_url.canonical_url)

        result = fetch_public_note(profile_parsed_url)

        self.assertEqual(result.note_type, "image")

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

    def test_clean_note_text_removes_trailing_video_hashtag_block(self) -> None:
        cleaned = clean_note_text(
            "Notion 已经用了五六年了，以及我是怎么使用 obsidian 的。 #效率神器 #notion #obsidian #笔记软件 #AI笔记 #电子笔记模板",
            "我为什么放弃了用了5年的Notion...?",
        )

        self.assertEqual(cleaned, "Notion 已经用了五六年了，以及我是怎么使用 obsidian 的。")

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

    def test_clean_note_text_removes_leading_hashtags_for_titleless_note(self) -> None:
        cleaned = clean_note_text(
            "#王向东老师#Ashtanga瑜伽 #阿斯汤加 #瑜伽 #北海 一般习练者都追求稳定中超常发挥。",
            "",
        )

        self.assertEqual(cleaned, "一般习练者都追求稳定中超常发挥。")

    def test_clean_note_text_removes_leading_hashtags_when_tightly_connected(self) -> None:
        cleaned = clean_note_text(
            "#标签1#标签2#标签3 正文从这里开始",
            "",
        )

        self.assertEqual(cleaned, "正文从这里开始")

    def test_clean_note_text_removes_tail_signature(self) -> None:
        cleaned = clean_note_text(
            "正文内容。 ——王向东",
            "",
        )

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_removes_tail_signature_with_time_and_location(self) -> None:
        cleaned = clean_note_text(
            "正文内容。 ——王向东\n昨天 18:52 广西",
            "",
        )

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_removes_tail_relative_time_and_location(self) -> None:
        cleaned = clean_note_text(
            "正文内容。 昨天 18:52 广西",
            "",
        )

        self.assertEqual(cleaned, "正文内容。")

    def test_clean_note_text_does_not_treat_author_as_title(self) -> None:
        cleaned = clean_note_text(
            "#王向东老师 #瑜伽 正文从这里开始",
            "",
        )

        self.assertEqual(cleaned, "正文从这里开始")

    def test_normalize_note_title_returns_none_for_empty_title(self) -> None:
        self.assertIsNone(normalize_note_title("", "北海阿斯汤加瑜伽"))

    def test_normalize_note_title_returns_none_when_title_equals_author(self) -> None:
        self.assertIsNone(normalize_note_title("北海阿斯汤加瑜伽", "北海阿斯汤加瑜伽"))

    def test_normalize_note_title_keeps_real_title(self) -> None:
        self.assertEqual(
            normalize_note_title("你以为孙哥在推荐闲鱼，其实是在给你上金融", "罐头的AI笔记"),
            "你以为孙哥在推荐闲鱼，其实是在给你上金融",
        )

    def test_clean_note_text_keeps_middle_hashtag_and_dash_content(self) -> None:
        cleaned = clean_note_text(
            "正文中间的 #Ashtanga 话题和——转折表达都应该保留，结尾也正常。",
            "",
        )

        self.assertEqual(cleaned, "正文中间的 #Ashtanga 话题和——转折表达都应该保留，结尾也正常。")

    def test_strip_redundant_leading_title_handles_spacing_difference(self) -> None:
        title = "我为什么放弃了用了5年的Notion...?"
        note_text = "我为什么放弃了用了 5 年的 Notion.?\n\nNotion 已经用了五六年了..."

        cleaned = strip_redundant_leading_title(note_text, title)

        self.assertEqual(cleaned, "Notion 已经用了五六年了...")

    def test_strip_redundant_leading_title_handles_punctuation_difference(self) -> None:
        title = "80后布局龙虾，身价越超千亿！"
        note_text = "80 后布局龙虾, 身价越超千亿!\n\n后续正文"

        cleaned = strip_redundant_leading_title(note_text, title)

        self.assertEqual(cleaned, "后续正文")

    def test_strip_redundant_leading_title_handles_case_difference(self) -> None:
        title = "Notion AI"
        note_text = "notion ai\n\n后续正文"

        cleaned = strip_redundant_leading_title(note_text, title)

        self.assertEqual(cleaned, "后续正文")

    def test_strip_redundant_leading_title_handles_html_entity_difference(self) -> None:
        title = "作用力：为什么我们开始需要&amp;quot;搭子&amp;quot;了？"
        note_text = '为什么我们开始需要"搭子"了？'

        cleaned = strip_redundant_leading_title(note_text, title)

        self.assertEqual(cleaned, "")

    def test_strip_redundant_leading_title_returns_empty_when_note_text_only_equals_title(self) -> None:
        title = "80后布局龙虾，身价越超千亿！"
        note_text = "80 后布局龙虾，身价越超千亿！"

        cleaned = strip_redundant_leading_title(note_text, title)

        self.assertEqual(cleaned, "")

    def test_strip_redundant_leading_title_strips_matching_short_opening_prefix_in_current_behavior(self) -> None:
        title = "Notion"
        note_text = "Notion 已经用了五六年了，它是我的主力工具。"

        cleaned = strip_redundant_leading_title(note_text, title)

        self.assertEqual(cleaned, "已经用了五六年了，它是我的主力工具。")

    @patch("xhs_public_fetcher.urlopen")
    def test_fetch_public_note_raises_on_network_failure(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = OSError("network down")

        with self.assertRaisesRegex(AppError, "公开页面抓取失败"):
            fetch_public_note(self.parsed_url)
