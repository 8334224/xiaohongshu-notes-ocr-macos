from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from clipboard_reader import read_clipboard_text
from downloader_utils import build_download_filename, cleanup_ocr_image_files, sanitize_filename_component
from main import run_existing_images_flow, run_from_clipboard_flow
from parser import parse_image_filename
from utils import AppError
from xhs_downloader import XiaohongshuDownloader
from xhs_url_validator import validate_xhs_note_url


class ClipboardAndDownloadTests(unittest.TestCase):
    def test_validate_url_rejects_non_xhs_url(self) -> None:
        with self.assertRaisesRegex(AppError, "不是支持的小红书"):
            validate_xhs_note_url("https://example.com/post/123")

    def test_validate_url_rejects_empty_text(self) -> None:
        with self.assertRaisesRegex(AppError, "剪贴板为空"):
            validate_xhs_note_url("")

    def test_validate_url_accepts_explore_shape(self) -> None:
        url = "https://www.xiaohongshu.com/explore/699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"

        normalized = validate_xhs_note_url(url)

        self.assertEqual(normalized, url)

    def test_validate_url_normalizes_profile_shape_to_explore(self) -> None:
        profile_url = (
            "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
            "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"
        )

        normalized = validate_xhs_note_url(profile_url)

        self.assertEqual(
            normalized,
            "https://www.xiaohongshu.com/explore/699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like",
        )

    def test_validate_url_normalizes_profile_and_explore_to_same_result(self) -> None:
        profile_url = (
            "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
            "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"
        )
        explore_url = "https://www.xiaohongshu.com/explore/699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like"

        self.assertEqual(validate_xhs_note_url(profile_url), validate_xhs_note_url(explore_url))

    def test_validate_url_rejects_invalid_profile_shape(self) -> None:
        with self.assertRaisesRegex(AppError, "不是支持的小红书图文笔记链接"):
            validate_xhs_note_url("https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/")

    def test_validate_url_preserves_query_parameters(self) -> None:
        profile_url = (
            "https://www.xiaohongshu.com/user/profile/5d3f838900000000120033a4/"
            "699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like&foo=bar"
        )

        normalized = validate_xhs_note_url(profile_url)

        self.assertEqual(
            normalized,
            "https://www.xiaohongshu.com/explore/699be056000000000c0349ff?xsec_token=abc&xsec_source=pc_like&foo=bar",
        )

    def test_sanitize_filename_component(self) -> None:
        self.assertEqual(sanitize_filename_component(' 标题:/?<>*_"测试" '), "标题 测试")

    @patch("clipboard_reader.subprocess.run")
    def test_read_clipboard_text_raises_when_empty(self, mock_run) -> None:
        mock_run.return_value = CompletedProcess(args=["pbpaste"], returncode=0, stdout="  ", stderr="")

        with self.assertRaisesRegex(AppError, "剪贴板为空"):
            read_clipboard_text()

    def test_cleanup_only_removes_supported_images(self) -> None:
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "a.jpg").write_bytes(b"x")
            (folder / "b.png").write_bytes(b"x")
            (folder / ".DS_Store").write_bytes(b"x")
            (folder / "notes.txt").write_text("keep", encoding="utf-8")

            removed = cleanup_ocr_image_files(folder)

            self.assertEqual(removed, ["a.jpg", "b.png"])
            self.assertFalse((folder / "a.jpg").exists())
            self.assertTrue((folder / ".DS_Store").exists())
            self.assertTrue((folder / "notes.txt").exists())

    def test_download_filename_stays_parser_compatible(self) -> None:
        filename = build_download_filename("年轻人/最好的时代", "李然:想当然", 2, "https://img.example.com/a.webp")
        parsed = parse_image_filename(Path(filename))

        self.assertEqual(parsed.title, "年轻人 最好的时代")
        self.assertEqual(parsed.author, "李然 想当然")
        self.assertEqual(parsed.page, 2)

    @patch("main.run_existing_images_flow")
    @patch("main.XiaohongshuDownloader")
    @patch("main.validate_xhs_note_url")
    @patch("main.read_clipboard_text")
    def test_clipboard_mode_enters_existing_ocr_flow(
        self,
        mock_read_clipboard,
        mock_validate_url,
        mock_downloader_cls,
        mock_run_existing_images_flow,
    ) -> None:
        mock_read_clipboard.return_value = "https://www.xiaohongshu.com/explore/abc123"
        mock_validate_url.return_value = "https://www.xiaohongshu.com/explore/abc123"
        mock_downloader_cls.return_value.download_from_url.return_value = [
            Path("/tmp/test_1_作者_来自小红书自动下载.jpg")
        ]
        with TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir) / "run"

            with patch("main.create_clipboard_workdir", return_value=workdir):
                mock_run_existing_images_flow.return_value = True
                run_from_clipboard_flow("OCR")

            mock_run_existing_images_flow.assert_called_once_with(workdir, "OCR", str(workdir / "output.txt"))

    @patch("main.run_existing_images_flow")
    @patch("main.XiaohongshuDownloader")
    @patch("main.validate_xhs_note_url")
    @patch("main.read_clipboard_text")
    def test_clipboard_mode_can_use_local_chrome(
        self,
        mock_read_clipboard,
        mock_validate_url,
        mock_downloader_cls,
        mock_run_existing_images_flow,
    ) -> None:
        mock_read_clipboard.return_value = "https://www.xiaohongshu.com/explore/abc123"
        mock_validate_url.return_value = "https://www.xiaohongshu.com/explore/abc123"
        mock_downloader_cls.return_value.download_from_url.return_value = [
            Path("/tmp/test_1_作者_来自小红书自动下载.jpg")
        ]
        with TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir) / "run"

            with patch("main.create_clipboard_workdir", return_value=workdir):
                mock_run_existing_images_flow.return_value = True
                run_from_clipboard_flow(
                    "OCR",
                    use_local_chrome=True,
                    chrome_cdp_url="http://127.0.0.1:9223",
                )

            mock_downloader_cls.assert_called_once_with(
                output_folder=workdir,
                debug_folder=workdir,
                use_local_chrome=True,
                chrome_cdp_url="http://127.0.0.1:9223",
            )
            mock_run_existing_images_flow.assert_called_once_with(workdir, "OCR", str(workdir / "output.txt"))

    def test_downloader_stores_local_chrome_options(self) -> None:
        downloader = XiaohongshuDownloader(use_local_chrome=True, chrome_cdp_url="http://127.0.0.1:9333")

        self.assertTrue(downloader.use_local_chrome)
        self.assertEqual(downloader.chrome_cdp_url, "http://127.0.0.1:9333")

    @patch("main.run_existing_images_flow")
    @patch("main.XiaohongshuDownloader")
    @patch("main.validate_xhs_note_url")
    @patch("main.read_clipboard_text")
    def test_clipboard_mode_success_removes_temp_workdir(
        self,
        mock_read_clipboard,
        mock_validate_url,
        mock_downloader_cls,
        mock_run_existing_images_flow,
    ) -> None:
        mock_read_clipboard.return_value = "https://www.xiaohongshu.com/explore/abc123"
        mock_validate_url.return_value = "https://www.xiaohongshu.com/explore/abc123"
        mock_downloader_cls.return_value.download_from_url.return_value = [Path("/tmp/fake.jpg")]
        mock_run_existing_images_flow.return_value = True

        with TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir) / "run"
            workdir.mkdir()
            (workdir / "dummy.txt").write_text("x", encoding="utf-8")

            with patch("main.create_clipboard_workdir", return_value=workdir):
                run_from_clipboard_flow("OCR")

            self.assertFalse(workdir.exists())

    @patch("main.run_existing_images_flow")
    @patch("main.XiaohongshuDownloader")
    @patch("main.validate_xhs_note_url")
    @patch("main.read_clipboard_text")
    def test_clipboard_mode_failure_keeps_temp_workdir(
        self,
        mock_read_clipboard,
        mock_validate_url,
        mock_downloader_cls,
        mock_run_existing_images_flow,
    ) -> None:
        mock_read_clipboard.return_value = "https://www.xiaohongshu.com/explore/abc123"
        mock_validate_url.return_value = "https://www.xiaohongshu.com/explore/abc123"
        mock_downloader_cls.return_value.download_from_url.return_value = [Path("/tmp/fake.jpg")]
        mock_run_existing_images_flow.side_effect = AppError("OCR failed")

        with TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir) / "run"
            workdir.mkdir()

            with patch("main.create_clipboard_workdir", return_value=workdir):
                with self.assertRaises(AppError):
                    run_from_clipboard_flow("OCR")

            self.assertTrue(workdir.exists())

    def test_run_existing_images_flow_can_use_custom_input_folder(self) -> None:
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "标题_1_作者_来自小红书自动下载.jpg").write_bytes(b"x")

            with patch("main.VisionOCR") as mock_ocr_cls, patch("main.NotesWriter") as mock_notes_writer_cls:
                mock_ocr_cls.return_value.recognize_text.return_value = "正文"
                mock_notes_writer_cls.return_value.create_note.return_value = None

                txt_path = folder / "output.txt"
                result = run_existing_images_flow(folder, "OCR", str(txt_path))

            self.assertTrue(result)
            self.assertTrue(txt_path.exists())

    def test_normalize_image_urls_deduplicates_by_canonical_url(self) -> None:
        urls = [
            "https://img.example.com/path/image.jpg?x-oss-process=image/resize,w_1080",
            "https://img.example.com/path/image.jpg?x-oss-process=image/resize,w_750",
            "https://img.example.com/path/image.jpg!large",
            "https://img.example.com/path/image2.jpg?foo=1",
        ]

        deduped = XiaohongshuDownloader._normalize_image_urls(urls)

        self.assertEqual(
            deduped,
            [
                "https://img.example.com/path/image.jpg?x-oss-process=image/resize,w_1080",
                "https://img.example.com/path/image2.jpg?foo=1",
            ],
        )

    def test_select_image_source_prefers_high_confidence_source(self) -> None:
        candidates = [
            {"url": "https://img.example.com/generic1.jpg", "source_type": "generic_img", "dom_context": "img", "sequence": "1"},
            {"url": "https://img.example.com/generic2.jpg", "source_type": "generic_img", "dom_context": "img", "sequence": "2"},
            {"url": "https://img.example.com/body1.jpg", "source_type": "embedded_data", "dom_context": "state.note.images[0]", "sequence": "3"},
            {"url": "https://img.example.com/body2.jpg", "source_type": "embedded_data", "dom_context": "state.note.images[1]", "sequence": "4"},
        ]

        selection = XiaohongshuDownloader._select_image_source(candidates)

        self.assertEqual(selection.source_type, "embedded_data")
        self.assertEqual(
            selection.urls,
            ["https://img.example.com/body1.jpg", "https://img.example.com/body2.jpg"],
        )

    def test_select_image_source_filters_clones_and_non_body_images(self) -> None:
        candidates = [
            {"url": "https://img.example.com/4.jpg", "source_type": "main_carousel", "dom_context": "swiper-slide swiper-slide-duplicate", "sequence": "1"},
            {"url": "https://img.example.com/1.jpg", "source_type": "main_carousel", "dom_context": "swiper-slide", "sequence": "2"},
            {"url": "https://img.example.com/2.jpg", "source_type": "main_carousel", "dom_context": "swiper-slide", "sequence": "3"},
            {"url": "https://img.example.com/3.jpg", "source_type": "main_carousel", "dom_context": "swiper-slide", "sequence": "4"},
            {"url": "https://img.example.com/1.jpg", "source_type": "main_carousel", "dom_context": "swiper-slide swiper-slide-duplicate", "sequence": "5"},
            {"url": "https://img.example.com/avatar.jpg", "source_type": "avatar", "dom_context": "user-avatar", "sequence": "6"},
            {"url": "https://img.example.com/thumb.jpg", "source_type": "thumbnail", "dom_context": "thumbnail-list", "sequence": "7"},
            {"url": "https://img.example.com/4.jpg", "source_type": "main_carousel", "dom_context": "swiper-slide", "sequence": "8"},
        ]

        selection = XiaohongshuDownloader._select_image_source(candidates)

        self.assertEqual(selection.source_type, "main_carousel")
        self.assertEqual(
            selection.urls,
            [
                "https://img.example.com/1.jpg",
                "https://img.example.com/2.jpg",
                "https://img.example.com/3.jpg",
                "https://img.example.com/4.jpg",
            ],
        )

    def test_select_image_source_restores_clone_only_missing_tail_image(self) -> None:
        candidates = [
            {"url": "https://img.example.com/4.jpg", "source_type": "main_carousel", "dom_context": "swiper-slide swiper-slide-duplicate swiper-slide-duplicate-prev", "sequence": "1"},
            {"url": "https://img.example.com/1.jpg", "source_type": "main_carousel", "dom_context": "swiper-slide", "sequence": "2"},
            {"url": "https://img.example.com/2.jpg", "source_type": "main_carousel", "dom_context": "swiper-slide", "sequence": "3"},
            {"url": "https://img.example.com/3.jpg", "source_type": "main_carousel", "dom_context": "swiper-slide", "sequence": "4"},
        ]

        selection = XiaohongshuDownloader._select_image_source(candidates)

        self.assertEqual(selection.source_type, "main_carousel")
        self.assertEqual(
            selection.urls,
            [
                "https://img.example.com/1.jpg",
                "https://img.example.com/2.jpg",
                "https://img.example.com/3.jpg",
                "https://img.example.com/4.jpg",
            ],
        )


if __name__ == "__main__":
    unittest.main()
