"""Utility helpers for Xiaohongshu image downloading."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from config import OCR_FOLDER, SUPPORTED_EXTENSIONS, XHS_DOWNLOAD_SUFFIX
from utils import AppError

INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')
MULTISPACE_PATTERN = re.compile(r"\s+")


def ensure_ocr_folder() -> Path:
    """Ensure the OCR folder exists for downloads."""
    OCR_FOLDER.mkdir(parents=True, exist_ok=True)
    return OCR_FOLDER


def sanitize_filename_component(value: str) -> str:
    """Sanitize a note title or author for safe local filenames."""
    cleaned = INVALID_FILENAME_CHARS.sub(" ", value.strip())
    cleaned = cleaned.replace("_", " ")
    cleaned = cleaned.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    cleaned = MULTISPACE_PATTERN.sub(" ", cleaned).strip(" .")
    if not cleaned:
        raise AppError("下载得到的标题或作者为空，无法生成兼容 OCR 的文件名。")
    return cleaned[:80]


def cleanup_ocr_image_files(folder: Path) -> list[str]:
    """Delete only supported image files from the OCR folder."""
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        return []

    removed: list[str] = []
    for path in sorted(p for p in folder.iterdir() if p.is_file()):
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            path.unlink()
            removed.append(path.name)
    return removed


def build_download_filename(title: str, author: str, page: int, image_url: str) -> str:
    """Build a parser-compatible filename for a downloaded Xiaohongshu image."""
    safe_title = sanitize_filename_component(title)
    safe_author = sanitize_filename_component(author)
    extension = detect_image_extension(image_url)
    return f"{safe_title}_{page}_{safe_author}_{XHS_DOWNLOAD_SUFFIX}{extension}"


def detect_image_extension(image_url: str) -> str:
    """Guess an image extension from the URL path."""
    suffix = Path(urlparse(image_url).path).suffix.lower()
    if suffix in SUPPORTED_EXTENSIONS:
        return suffix
    return ".jpg"
