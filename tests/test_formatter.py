from datetime import datetime
from pathlib import Path
import unittest

from formatter import build_note_body, build_note_title
from parser import ParsedImage
from utils import clean_ocr_text


class FormatterTests(unittest.TestCase):
    def test_builds_complete_note_body(self) -> None:
        images = [
            ParsedImage(Path("标题_1_作者_来自小红书网页版.jpg"), "标题", "作者", 1),
            ParsedImage(Path("标题_2_作者_来自小红书网页版.jpg"), "标题", "作者", 2),
        ]
        body = build_note_body(
            "/Users/test/Desktop/OCR",
            datetime(2026, 3, 11, 15, 42),
            images,
            ["第一页 OCR 文本", "第二页 OCR 文本"],
        )

        self.assertIn("第一页 OCR 文本", body)
        self.assertIn("第二页 OCR 文本", body)
        self.assertNotIn("来源文件夹", body)
        self.assertNotIn("生成时间", body)
        self.assertNotIn("图片数量", body)
        self.assertNotIn("【第1张｜", body)
        self.assertNotIn("标题_1_作者_来自小红书网页版.jpg", body)
        self.assertEqual(body, "第一页 OCR 文本第二页 OCR 文本")
        self.assertNotIn("\n\n第二页 OCR 文本", body)

    def test_build_note_body_joins_pages_without_boundary_whitespace(self) -> None:
        images = [
            ParsedImage(Path("标题_1_作者_来自小红书网页版.jpg"), "标题", "作者", 1),
            ParsedImage(Path("标题_2_作者_来自小红书网页版.jpg"), "标题", "作者", 2),
            ParsedImage(Path("标题_3_作者_来自小红书网页版.jpg"), "标题", "作者", 3),
        ]
        body = build_note_body(
            "/Users/test/Desktop/OCR",
            datetime(2026, 3, 11, 15, 42),
            images,
            ["第一页结尾   ", "\n第二页中间  ", "\n\n第三页开头"],
        )

        self.assertTrue(body.endswith("第一页结尾第二页中间第三页开头"))
        self.assertNotIn("第一页结尾 第二页中间", body)
        self.assertNotIn("第一页结尾\n第二页中间", body)

    def test_build_note_title_uses_author_and_article_title(self) -> None:
        note_title = build_note_title("  现在是年轻人最好的时代啊  ", " 李然想当然 ", datetime(2026, 3, 11, 15, 42))

        self.assertEqual(note_title, "李然想当然：现在是年轻人最好的时代啊")

    def test_clean_ocr_text_preserves_paragraphs_conservatively(self) -> None:
        cleaned = clean_ocr_text(" 第一行  \n第二行\n\n\n 第三段 \n continuation \n\n")

        self.assertEqual(cleaned, "第一行第二行\n\n第三段\ncontinuation")

    def test_clean_ocr_text_inserts_space_for_english_line_merge(self) -> None:
        cleaned = clean_ocr_text("for\nnew\n\nfresh\nmind")

        self.assertEqual(cleaned, "for new\n\nfresh mind")

    def test_clean_ocr_text_removes_standalone_punctuation_lines(self) -> None:
        cleaned = clean_ocr_text("第一句\n，\n第二句\n。\n第三句")

        self.assertEqual(cleaned, "第一句\n第二句\n第三句")
        self.assertNotIn("\n，\n", cleaned)
        self.assertNotIn("\n。\n", cleaned)

    def test_clean_ocr_text_collapses_repeated_punctuation(self) -> None:
        cleaned = clean_ocr_text("你好，，\n世界。。\nWow!!\nTest??")

        self.assertEqual(cleaned, "你好，世界。\nWow!\nTest?")

    def test_clean_ocr_text_adds_space_between_chinese_and_english(self) -> None:
        cleaned = clean_ocr_text("年轻new grad\n很多fresh mind")

        self.assertEqual(cleaned, "年轻 new grad\n很多 fresh mind")

    def test_clean_ocr_text_adds_space_between_chinese_and_numbers(self) -> None:
        cleaned = clean_ocr_text("像5到10年前")

        self.assertEqual(cleaned, "像 5 到 10 年前")

    def test_clean_ocr_text_adds_space_between_english_and_chinese(self) -> None:
        cleaned = clean_ocr_text("new grads最好的时代")

        self.assertEqual(cleaned, "new grads 最好的时代")

    def test_clean_ocr_text_preserves_english_phrase_spacing(self) -> None:
        cleaned = clean_ocr_text("fresh mind for new grads")

        self.assertEqual(cleaned, "fresh mind for new grads")

    def test_clean_ocr_text_does_not_add_space_around_chinese_punctuation(self) -> None:
        cleaned = clean_ocr_text("你好，world。")

        self.assertEqual(cleaned, "你好，world。")

    def test_clean_ocr_text_merges_short_continuation_line(self) -> None:
        cleaned = clean_ocr_text("客观来讲，\nfresh mind 和 experience 都是双刃剑")

        self.assertEqual(cleaned, "客观来讲，fresh mind 和 experience 都是双刃剑")

    def test_clean_ocr_text_strips_leading_noise_punctuation(self) -> None:
        cleaned = clean_ocr_text('，experience 的风险是"以为自己知道"\n。这是下一句')

        self.assertEqual(cleaned, 'experience 的风险是"以为自己知道"\n这是下一句')

    def test_clean_ocr_text_does_not_merge_across_blank_line(self) -> None:
        cleaned = clean_ocr_text("客观来讲，\n\nfresh mind 和 experience 都是双刃剑")

        self.assertEqual(cleaned, "客观来讲，\n\nfresh mind 和 experience 都是双刃剑")


if __name__ == "__main__":
    unittest.main()
