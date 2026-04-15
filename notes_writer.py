"""Obsidian Markdown note writer."""

from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict
from pathlib import Path

from utils import AppError

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())

try:  # pragma: no cover - optional dependency
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = None

_FILENAME_UNSAFE = re.compile(r'[/\\:*?"<>|]')


class NotesWriter:
    """Create Obsidian Markdown notes by writing .md files."""

    def __init__(
        self,
        folder: str | Path,
        append_index: bool = True,
        delay_seconds: float = 0.2,
        show_progress: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.folder = Path(folder)
        self.append_index = append_index
        self.delay_seconds = max(0.0, delay_seconds)
        self.show_progress = show_progress
        self.logger = logger or LOGGER
        self.failed_notes: list[str] = []

    def create_note(self, title: str, body: str) -> None:
        """Create a new Markdown note in the configured folder."""
        self.folder.mkdir(parents=True, exist_ok=True)
        filename = self._safe_filename(title or "Untitled")
        path = self._unique_path(filename)
        content = f"# {title}\n\n{body}\n" if title else f"{body}\n"
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise AppError(f"Obsidian 笔记写入失败：{path}，{exc}") from exc
        self.logger.info("Obsidian 笔记已写入：%s", path)

    def write_paragraphs(self, paragraphs: list[str], base_title: str = "Note") -> dict[str, bool]:
        """Create one Markdown note per non-empty paragraph and return per-note status."""
        self.failed_notes = []
        prepared_bodies = [
            paragraph.strip()
            for paragraph in paragraphs
            if isinstance(paragraph, str) and paragraph.strip()
        ]
        prepared_items = [
            (self._build_note_title(base_title, index), body)
            for index, body in enumerate(prepared_bodies, start=1)
        ]
        results: OrderedDict[str, bool] = OrderedDict()
        if not prepared_items:
            self.logger.info("没有可写入的有效段落，已跳过。")
            return results

        iterator = prepared_items
        if self.show_progress and tqdm is not None:
            iterator = tqdm(prepared_items, desc="Writing Notes", unit="note")

        total = len(prepared_items)
        for index, (title, body) in enumerate(iterator, start=1):
            try:
                self.create_note(title, body)
            except AppError as exc:
                self.failed_notes.append(title)
                results[title] = False
                self.logger.error("Obsidian 笔记写入失败：title=%s error=%s", title, exc)
            else:
                results[title] = True

            if self.delay_seconds > 0 and index < total:
                time.sleep(self.delay_seconds)

        return results

    def _build_note_title(self, base_title: str, index: int) -> str:
        """Build the final note title for a paragraph entry."""
        title = (base_title or "Note").strip() or "Note"
        if not self.append_index:
            return title
        return f"{title} {index}"

    def _unique_path(self, filename: str) -> Path:
        """Return a unique file path, appending a number if the file already exists."""
        path = self.folder / f"{filename}.md"
        if not path.exists():
            return path
        counter = 2
        while True:
            path = self.folder / f"{filename} {counter}.md"
            if not path.exists():
                return path
            counter += 1

    @staticmethod
    def _safe_filename(title: str) -> str:
        """Sanitize a title into a safe filename."""
        cleaned = _FILENAME_UNSAFE.sub("-", title.strip())
        cleaned = cleaned.strip(". ")
        return cleaned or "Untitled"
