"""Filename parsing and batch validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from config import MAX_IMAGES, SUPPORTED_EXTENSIONS
from utils import AppError, ensure_directory_exists

FILENAME_PATTERN = re.compile(
    r"^(?P<title>.+?)_(?P<page>\d+)_(?P<author>[^_]+)_来自小红书(?:网页版|自动下载)\.(?P<ext>jpg|jpeg|png|webp|heic)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedImage:
    """Parsed metadata for a single image file."""

    path: Path
    title: str
    author: str
    page: int


@dataclass(frozen=True)
class ScanResult:
    """Validated image batch and ignored non-image files."""

    images: list[ParsedImage]
    ignored_files: list[str]


def parse_image_filename(path: Path) -> ParsedImage:
    """Parse a Xiaohongshu image filename into structured metadata."""
    match = FILENAME_PATTERN.fullmatch(path.name)
    if not match:
        raise AppError(f"文件名无法按规则解析：{path.name}")

    title = match.group("title").strip()
    author = match.group("author").strip()
    page = int(match.group("page"))
    if not title:
        raise AppError(f"文件名标题为空：{path.name}")
    if not author:
        raise AppError(f"文件名作者为空：{path.name}")

    return ParsedImage(path=path, title=title, author=author, page=page)


def scan_and_validate_images(folder: Path) -> list[ParsedImage]:
    """Scan the OCR folder and return a validated, sorted image batch."""
    return scan_and_validate_images_with_report(folder).images


def scan_and_validate_images_with_report(folder: Path) -> ScanResult:
    """Scan the OCR folder, validate supported images, and report ignored files."""
    ensure_directory_exists(folder)

    all_entries = sorted(p for p in folder.iterdir() if p.is_file())
    if not all_entries:
        raise AppError(f"OCR 文件夹为空：{folder}")

    ignored_name_entries = [p for p in all_entries if _should_ignore_input_file(p)]
    remaining_entries = [p for p in all_entries if not _should_ignore_input_file(p)]
    image_entries = [p for p in remaining_entries if p.suffix.lower() in SUPPORTED_EXTENSIONS]
    ignored_files = [p.name for p in remaining_entries if p.suffix.lower() not in SUPPORTED_EXTENSIONS]
    ignored_files.extend(p.name for p in ignored_name_entries)

    if not image_entries:
        raise AppError(f"OCR 文件夹中没有可处理的图片：{folder}")

    if len(image_entries) > MAX_IMAGES:
        raise AppError(f"图片数量超过上限 {MAX_IMAGES}：当前 {len(image_entries)} 张")

    parsed = [parse_image_filename(path) for path in image_entries]
    _validate_same_title(parsed)

    images = sorted(parsed, key=lambda item: (item.page, item.path.name))
    return ScanResult(images=images, ignored_files=ignored_files)


def _validate_same_title(images: Iterable[ParsedImage]) -> None:
    """Ensure all parsed images belong to the same note title."""
    titles = {item.title for item in images}
    if len(titles) != 1:
        raise AppError(f"检测到多个不同标题：{', '.join(sorted(titles))}")


def _should_ignore_input_file(path: Path) -> bool:
    """Ignore debug artifacts and known local output files in OCR input scanning."""
    name = path.name
    return name.startswith("debug_") or name == "output.txt"
