from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from parser import parse_image_filename, scan_and_validate_images, scan_and_validate_images_with_report
from utils import AppError


class ParserTests(unittest.TestCase):
    def test_parse_three_valid_filenames(self) -> None:
        parsed = parse_image_filename(
            Path("纳瓦尔最新访谈：只要你会说话，你就是巫师_3_第二大脑计划_来自小红书网页版.jpg")
        )
        self.assertEqual(parsed.title, "纳瓦尔最新访谈：只要你会说话，你就是巫师")
        self.assertEqual(parsed.author, "第二大脑计划")
        self.assertEqual(parsed.page, 3)

    def test_sorts_by_page_then_filename(self) -> None:
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "标题_2_作者_来自小红书网页版.jpg").write_bytes(b"x")
            (folder / "标题_1_作者_来自小红书网页版.jpg").write_bytes(b"x")
            (folder / "标题_2_另一个作者_来自小红书网页版.jpg").write_bytes(b"x")

            images = scan_and_validate_images(folder)

            self.assertEqual(
                [item.path.name for item in images],
                [
                    "标题_1_作者_来自小红书网页版.jpg",
                    "标题_2_作者_来自小红书网页版.jpg",
                    "标题_2_另一个作者_来自小红书网页版.jpg",
                ],
            )

    def test_detects_multiple_titles(self) -> None:
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "标题A_1_作者_来自小红书网页版.jpg").write_bytes(b"x")
            (folder / "标题B_2_作者_来自小红书网页版.jpg").write_bytes(b"x")

            with self.assertRaisesRegex(AppError, "多个不同标题"):
                scan_and_validate_images(folder)

    def test_detects_empty_folder(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(AppError, "文件夹为空"):
                scan_and_validate_images(Path(temp_dir))

    def test_detects_too_many_images(self) -> None:
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            for index in range(1, 33):
                (folder / f"标题_{index}_作者_来自小红书网页版.jpg").write_bytes(b"x")

            with self.assertRaisesRegex(AppError, "超过上限 31"):
                scan_and_validate_images(folder)

    def test_raises_when_filename_is_invalid(self) -> None:
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "不符合规则.jpg").write_bytes(b"x")

            with self.assertRaisesRegex(AppError, "无法按规则解析"):
                scan_and_validate_images(folder)

    def test_ignores_non_image_files_and_processes_supported_images(self) -> None:
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / ".DS_Store").write_bytes(b"x")
            (folder / "notes.txt").write_text("hello", encoding="utf-8")
            (folder / "标题_1_作者_来自小红书网页版.jpg").write_bytes(b"x")
            (folder / "标题_2_作者_来自小红书网页版.png").write_bytes(b"x")

            result = scan_and_validate_images_with_report(folder)

            self.assertEqual(
                [item.path.name for item in result.images],
                ["标题_1_作者_来自小红书网页版.jpg", "标题_2_作者_来自小红书网页版.png"],
            )
            self.assertEqual(result.ignored_files, [".DS_Store", "notes.txt"])

    def test_raises_zero_images_when_folder_has_only_non_image_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / ".DS_Store").write_bytes(b"x")
            (folder / "notes.txt").write_text("hello", encoding="utf-8")
            (folder / "doc.pdf").write_bytes(b"x")

            with self.assertRaisesRegex(AppError, "没有可处理的图片"):
                scan_and_validate_images(folder)

    def test_non_image_files_do_not_participate_in_validation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "标题_1_作者_来自小红书网页版.jpg").write_bytes(b"x")
            (folder / "错误标题B_2_作者_来自小红书网页版.pdf").write_bytes(b"x")
            (folder / "不符合规则.txt").write_text("bad", encoding="utf-8")

            images = scan_and_validate_images(folder)

            self.assertEqual([item.path.name for item in images], ["标题_1_作者_来自小红书网页版.jpg"])

    def test_ignores_debug_artifacts_in_ocr_folder(self) -> None:
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "debug_xhs_page.png").write_bytes(b"x")
            (folder / "output.txt").write_text("keep", encoding="utf-8")
            (folder / "标题_1_作者_来自小红书网页版.jpg").write_bytes(b"x")

            result = scan_and_validate_images_with_report(folder)

            self.assertEqual([item.path.name for item in result.images], ["标题_1_作者_来自小红书网页版.jpg"])
            self.assertEqual(sorted(result.ignored_files), ["debug_xhs_page.png", "output.txt"])


if __name__ == "__main__":
    unittest.main()
