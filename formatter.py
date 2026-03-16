"""Format OCR output for Notes."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from datetime import datetime

from parser import ParsedImage


def build_note_title(note_title: str, author: str, generated_at: datetime) -> str:
    """Build the Notes entry title."""
    del generated_at
    cleaned_title = note_title.strip()
    cleaned_author = author.strip()
    if not cleaned_title:
        raise ValueError("note title is empty")
    if not cleaned_author:
        raise ValueError("author is empty")
    return f"{cleaned_author}：{cleaned_title}"


def build_note_body(
    source_folder: str,
    generated_at: datetime,
    images: list[ParsedImage],
    ocr_texts: list[str],
    note_text: str | None = None,
) -> str:
    """Build the Notes entry body as one continuous article."""
    if len(images) != len(ocr_texts):
        raise ValueError("images and ocr_texts length mismatch")
    del source_folder
    del generated_at
    del images
    return _merge_note_and_ocr(note_text, _join_page_texts(ocr_texts))


def _join_page_texts(ocr_texts: list[str]) -> str:
    """Join page texts directly without inserting extra page separators."""
    parts = [text for text in ocr_texts if text.strip()]
    if not parts:
        return ""

    merged = parts[0].strip()
    for text in parts[1:]:
        merged = merged.rstrip() + text.lstrip()
    return merged


def _merge_note_and_ocr(note_text: str | None, ocr_text: str) -> str:
    """Merge note text and OCR text in the final note body."""
    cleaned_note_text = (note_text or "").strip()
    cleaned_ocr_text = ocr_text.strip()
    if cleaned_note_text and cleaned_ocr_text:
        if _is_highly_redundant(cleaned_note_text, cleaned_ocr_text):
            return cleaned_note_text
        return f"{cleaned_note_text}\n\n{cleaned_ocr_text}"
    return cleaned_note_text or cleaned_ocr_text


def _is_highly_redundant(note_text: str, ocr_text: str) -> bool:
    """Return whether OCR text is effectively duplicated by note text."""
    normalized_note_text = _normalize_for_dedup(note_text)
    normalized_ocr_text = _normalize_for_dedup(ocr_text)
    if not normalized_note_text or not normalized_ocr_text:
        return False
    if normalized_ocr_text in normalized_note_text:
        return True
    shorter_length = min(len(normalized_note_text), len(normalized_ocr_text))
    longer_length = max(len(normalized_note_text), len(normalized_ocr_text))
    if (
        normalized_note_text in normalized_ocr_text
        and shorter_length > 0
        and (longer_length - shorter_length) / shorter_length <= 1.25
    ):
        return True
    compact_note_text = normalized_note_text.replace(" ", "")
    compact_ocr_text = normalized_ocr_text.replace(" ", "")
    if compact_note_text and compact_ocr_text:
        if compact_ocr_text in compact_note_text:
            return True
        if compact_note_text in compact_ocr_text:
            return True
        if SequenceMatcher(None, compact_note_text, compact_ocr_text).ratio() >= 0.9:
            return True
    return SequenceMatcher(None, normalized_note_text, normalized_ocr_text).ratio() >= 0.9


def _normalize_for_dedup(text: str) -> str:
    """Normalize text lightly before duplicate detection."""
    collapsed = re.sub(r"\s+", " ", text.strip()).lower()
    return re.sub(r"[，。！？；：、“”‘’（）【】《》〈〉,.!?;:'\"()\\[\\]{}<>·`~@#$%^&*_+=|\\\\/-]+", "", collapsed)
