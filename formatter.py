"""Format OCR output for Notes."""

from __future__ import annotations

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
) -> str:
    """Build the Notes entry body as one continuous article."""
    if len(images) != len(ocr_texts):
        raise ValueError("images and ocr_texts length mismatch")
    del source_folder
    del generated_at
    del images
    body_text = _join_page_texts(ocr_texts)
    return body_text


def _join_page_texts(ocr_texts: list[str]) -> str:
    """Join page texts directly without inserting extra page separators."""
    parts = [text for text in ocr_texts if text.strip()]
    if not parts:
        return ""

    merged = parts[0].strip()
    for text in parts[1:]:
        merged = merged.rstrip() + text.lstrip()
    return merged
