from __future__ import annotations

import unittest

from text_cleaner import TextCleaner


class TextCleanerTests(unittest.TestCase):
    def test_clean_text_returns_empty_for_empty_input(self) -> None:
        cleaner = TextCleaner()

        self.assertEqual(cleaner.clean_text(""), "")
        self.assertEqual(cleaner.clean_text(None), "")

    def test_clean_text_raises_for_non_string_input(self) -> None:
        cleaner = TextCleaner()

        with self.assertRaises(TypeError):
            cleaner.clean_text(123)  # type: ignore[arg-type]

    def test_clean_text_removes_duplicate_lines_and_blank_lines(self) -> None:
        cleaner = TextCleaner(remove_emoji=False, remove_duplicates=True)

        cleaned = cleaner.clean_text("第一行\n\n第一行\n\n第二行\n\n\n第二行")

        self.assertEqual(cleaned, "第一行\n\n第二行")

    def test_clean_text_removes_emoji(self) -> None:
        cleaner = TextCleaner(remove_emoji=True, remove_duplicates=False)

        cleaned = cleaner.clean_text("你好😀\n世界🚀")

        self.assertEqual(cleaned, "你好\n世界")

    def test_structure_text_splits_paragraphs_in_order(self) -> None:
        cleaner = TextCleaner(remove_emoji=False, remove_duplicates=False, preserve_paragraphs=True)

        structured = cleaner.structure_text("第一段内容。\n\n第二段内容。\n\n第三段内容。")

        self.assertEqual(structured, ["第一段内容。", "第二段内容。", "第三段内容。"])

    def test_structure_text_returns_single_item_when_not_preserving_paragraphs(self) -> None:
        cleaner = TextCleaner(remove_emoji=False, remove_duplicates=False, preserve_paragraphs=False)

        structured = cleaner.structure_text("第一段内容。\n\n第二段内容。")

        self.assertEqual(structured, ["第一段内容。 第二段内容。"])
