"""Shared utility helpers."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

SHORT_LINE_CONTINUATION_MAX = 12


class AppError(Exception):
    """Base exception for user-facing failures."""


def ensure_directory_exists(path: Path) -> None:
    """Ensure the configured OCR directory exists."""
    if not path.exists():
        raise AppError(f"OCR 文件夹不存在：{path}")
    if not path.is_dir():
        raise AppError(f"OCR 路径不是文件夹：{path}")


def clean_ocr_text(text: str) -> str:
    """Apply conservative OCR cleanup while preserving paragraph boundaries."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    stripped_lines = [line.strip() for line in normalized.split("\n")]

    collapsed_lines: list[str] = []
    previous_blank = False
    for line in stripped_lines:
        is_blank = line == ""
        if is_blank:
            if not previous_blank:
                collapsed_lines.append("")
            previous_blank = True
            continue

        if collapsed_lines and collapsed_lines[-1] and _should_merge_lines(collapsed_lines[-1], line):
            collapsed_lines[-1] = _merge_lines(collapsed_lines[-1], line)
        else:
            collapsed_lines.append(line)
        previous_blank = False

    cleaned_lines = [
        _normalize_mixed_spacing(_normalize_line_noise(_strip_leading_noise_punctuation(line)))
        for line in collapsed_lines
        if not _is_noise_only_line(line)
    ]
    return "\n".join(cleaned_lines).strip()


def clean_note_text(note_text: str, title: str = "") -> str:
    """Clean note text conservatively for Xiaohongshu正文提取."""
    cleaned = clean_ocr_text(note_text)
    if not cleaned:
        return ""

    cleaned = _strip_repeated_title_prefix(cleaned, title)
    cleaned = _strip_tail_hashtag_block(cleaned)
    cleaned = _strip_tail_metadata(cleaned)
    return cleaned.strip()


def export_text_file(path: Path, content: str) -> None:
    """Write note content to a local txt file."""
    path.write_text(content, encoding="utf-8")


def _strip_repeated_title_prefix(note_text: str, title: str) -> str:
    """Remove a repeated title or title core phrase from the beginning of note text."""
    cleaned_title = clean_ocr_text(title).strip()
    if not cleaned_title:
        return note_text

    candidates = [cleaned_title]
    core_title = _extract_core_title_phrase(cleaned_title)
    if core_title and core_title not in candidates:
        candidates.append(core_title)

    for candidate in candidates:
        if note_text.startswith(candidate):
            stripped = note_text[len(candidate) :].lstrip(" \t\r\n：:，,。.!！?？-—_|")
            if stripped:
                return stripped
    return note_text


def _extract_core_title_phrase(title: str) -> str:
    """Extract the last semantic title segment using common separators."""
    parts = [part.strip() for part in re.split(r"[：:\-—_|]", title) if part.strip()]
    return parts[-1] if parts else title.strip()


def _strip_tail_hashtag_block(note_text: str) -> str:
    """Remove a trailing Xiaohongshu hashtag block."""
    metadata_pattern = (
        r"(?:\s*(?:编辑于|发布于)\s*)?"
        r"(?:(?:\d+\s*(?:分钟|小时|天)前)|(?:\d+(?:分钟|小时|天)前)|昨天|今天|刚刚"
        r"|(?:\d{4}[-/])?\d{1,2}[-/]\d{1,2})(?:\s*[\u4E00-\u9FFF]{1,12})?\s*$"
    )
    text_without_metadata = re.sub(metadata_pattern, "", note_text).rstrip()
    match = re.search(r"(?:^|[\s。！？!?])(#\S+(?:\s+#\S+)*)\s*$", text_without_metadata)
    if not match:
        return note_text.strip()
    return text_without_metadata[: match.start(1)].rstrip()


def _strip_tail_metadata(note_text: str) -> str:
    """Remove trailing publish/edit time and optional location metadata."""
    return re.sub(
        r"(?:\s*(?:编辑于|发布于)\s*)?"
        r"(?:(?:\d+\s*(?:分钟|小时|天)前)|(?:\d+(?:分钟|小时|天)前)|昨天|今天|刚刚"
        r"|(?:\d{4}[-/])?\d{1,2}[-/]\d{1,2})(?:\s*[\u4E00-\u9FFF]{1,12})?\s*$",
        "",
        note_text,
    ).strip()


def _should_merge_lines(previous_line: str, current_line: str) -> bool:
    """Merge only when a hard line break is likely unnatural."""
    if not previous_line or not current_line:
        return False

    if _looks_like_new_paragraph(current_line):
        return False
    if previous_line[-1].isspace() or current_line[0].isspace():
        return False
    if _should_merge_short_continuation(previous_line, current_line):
        return True
    if previous_line.endswith(("。", "！", "？", "；", "：", ".", "!", "?", ";", ":", "】")):
        return False
    if re.search(r"[A-Za-z0-9]$", previous_line) and re.match(r"^[A-Za-z0-9]", current_line):
        return True
    if _is_cjk(previous_line[-1]) and _is_cjk(current_line[0]):
        return True
    return False


def _merge_lines(previous_line: str, current_line: str) -> str:
    """Merge two adjacent OCR lines conservatively."""
    if re.search(r"[A-Za-z]$", previous_line) and re.match(r"^[A-Za-z]", current_line):
        return f"{previous_line} {current_line}"
    return f"{previous_line}{current_line}"


def _is_noise_only_line(line: str) -> bool:
    """Return whether the line is a single standalone punctuation mark."""
    return bool(re.fullmatch(r"[，。！？；：,.!?;:]", line))


def _normalize_line_noise(line: str) -> str:
    """Collapse obviously duplicated punctuation within one line."""
    return re.sub(r"([，。！？；：,.!?;:])\1+", r"\1", line)


def _strip_leading_noise_punctuation(line: str) -> str:
    """Remove obvious stray leading punctuation before normal text."""
    return re.sub(r'^[，。！？；：,.!?;:]+(?=[\u4E00-\u9FFFA-Za-z0-9])', "", line)


def _normalize_mixed_spacing(line: str) -> str:
    """Insert spaces at obvious CJK and ASCII word/number boundaries."""
    line = re.sub(r"([\u4E00-\u9FFF])([A-Za-z0-9])", r"\1 \2", line)
    line = re.sub(r"([A-Za-z0-9])([\u4E00-\u9FFF])", r"\1 \2", line)
    return line


def _should_merge_short_continuation(previous_line: str, current_line: str) -> bool:
    """Merge a short lead-in line ending with a continuation-style punctuation mark."""
    return (
        len(previous_line) <= SHORT_LINE_CONTINUATION_MAX
        and previous_line.endswith(("，", "：", "、", "（", "“", ",", ":", "("))
    )


def _looks_like_new_paragraph(line: str) -> bool:
    """Return whether a line looks like a heading or list item."""
    if line.startswith(("【", "-", "•", "*", "#")):
        return True
    return bool(re.match(r"^\d+[.)、:：]", line))


def _is_cjk(char: str) -> bool:
    """Return whether a character is in a common CJK Unicode block."""
    codepoint = ord(char)
    return 0x4E00 <= codepoint <= 0x9FFF


def now() -> datetime:
    """Return the current local datetime."""
    return datetime.now()
