"""Post-processing helpers for OCR text cleanup and lightweight structuring."""

from __future__ import annotations

import logging
import re

from utils import clean_ocr_text

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())

try:  # pragma: no cover - optional dependency
    import emoji as emoji_lib
except ImportError:  # pragma: no cover
    emoji_lib = None

try:  # pragma: no cover - optional dependency
    import regex as regex_lib
except ImportError:  # pragma: no cover
    regex_lib = None


class TextCleaner:
    """Clean OCR text and optionally structure it into paragraphs."""

    def __init__(
        self,
        remove_emoji: bool = True,
        remove_duplicates: bool = True,
        preserve_paragraphs: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self.remove_emoji = remove_emoji
        self.remove_duplicates = remove_duplicates
        self.preserve_paragraphs = preserve_paragraphs
        self.logger = logger or LOGGER

    def clean_text(self, raw_text: str) -> str:
        """Return cleaned OCR text."""
        if raw_text is None:
            return ""
        if not isinstance(raw_text, str):
            raise TypeError("raw_text must be a string")

        normalized = clean_ocr_text(raw_text)
        if not normalized:
            return ""

        if self.remove_emoji:
            normalized = self._remove_emoji(normalized)
        normalized = self._remove_control_chars(normalized)
        if self.remove_duplicates:
            normalized = self._remove_duplicate_lines(normalized)
        normalized = self._collapse_blank_lines(normalized)
        if not self.preserve_paragraphs:
            normalized = re.sub(r"\n+", " ", normalized)
        return normalized.strip()

    def structure_text(self, raw_text: str) -> list[str]:
        """Split cleaned text into paragraphs while preserving order."""
        cleaned = self.clean_text(raw_text)
        if not cleaned:
            return []
        if self.preserve_paragraphs:
            return [part.strip() for part in re.split(r"\n{2,}", cleaned) if part.strip()]
        return [cleaned]

    def _remove_emoji(self, text: str) -> str:
        """Remove emoji using optional dependencies or a unicode-range fallback."""
        if not text:
            return text
        if emoji_lib is not None:  # pragma: no branch
            return emoji_lib.replace_emoji(text, replace="")
        if regex_lib is not None:
            return regex_lib.sub(r"\p{Extended_Pictographic}", "", text)
        return re.sub(
            r"[\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
            r"\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF"
            r"\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF\U00002700-\U000027BF"
            r"\U00002600-\U000026FF]+",
            "",
            text,
        )

    @staticmethod
    def _remove_duplicate_lines(text: str) -> str:
        """Drop duplicate non-empty lines while preserving the first occurrence order."""
        seen: set[str] = set()
        cleaned_lines: list[str] = []
        for line in text.split("\n"):
            key = line.strip()
            if not key:
                cleaned_lines.append("")
                continue
            if key in seen:
                continue
            seen.add(key)
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    @staticmethod
    def _collapse_blank_lines(text: str) -> str:
        """Collapse repeated blank lines into a single paragraph separator."""
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @staticmethod
    def _remove_control_chars(text: str) -> str:
        """Remove control chars while keeping line breaks and tabs harmless."""
        return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
