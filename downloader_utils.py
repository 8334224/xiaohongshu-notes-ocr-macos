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


def build_download_filename(title: str, author: str, page: int, image_url: str, content_type: str | None = None) -> str:
    """Build a parser-compatible filename for a downloaded Xiaohongshu image."""
    safe_title = sanitize_filename_component(title)
    safe_author = sanitize_filename_component(author)
    extension = detect_image_extension(image_url, content_type=content_type)
    return f"{safe_title}_{page}_{safe_author}_{XHS_DOWNLOAD_SUFFIX}{extension}"


def build_download_stem(title: str, author: str, page: int) -> str:
    """Build a parser-compatible filename stem without an extension."""
    safe_title = sanitize_filename_component(title)
    safe_author = sanitize_filename_component(author)
    return f"{safe_title}_{page}_{safe_author}_{XHS_DOWNLOAD_SUFFIX}"


def detect_image_extension(image_url: str, content_type: str | None = None) -> str:
    """Guess an image extension from content type first, then URL hints."""
    content_type_extension = _extension_from_content_type(content_type)
    if content_type_extension:
        return content_type_extension

    lowered_url = image_url.lower()
    suffix = Path(urlparse(image_url).path).suffix.lower()
    if suffix in SUPPORTED_EXTENSIONS:
        return suffix
    if "webp" in lowered_url:
        return ".webp"
    if "jpeg" in lowered_url or "jpg" in lowered_url:
        return ".jpg"
    if "png" in lowered_url:
        return ".png"
    return ".webp"


def _extension_from_content_type(content_type: str | None) -> str | None:
    """Map HTTP image content types to supported filename suffixes."""
    if not content_type:
        return None

    normalized = content_type.split(";", 1)[0].strip().lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "image/heif": ".heic",
    }
    return mapping.get(normalized)
