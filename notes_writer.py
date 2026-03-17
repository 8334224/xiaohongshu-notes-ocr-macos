"""Apple Notes writer via AppleScript."""

from __future__ import annotations

import html
import logging
import subprocess
import time
from collections import OrderedDict

from utils import AppError

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())

try:  # pragma: no cover - optional dependency
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = None

APPLE_SCRIPT = r'''
on run argv
    set noteTitle to item 1 of argv
    set noteBody to item 2 of argv
    set targetFolderName to item 3 of argv

    tell application "Notes"
        activate

        set targetFolder to missing value
        repeat with eachFolder in folders
            if name of eachFolder is targetFolderName then
                set targetFolder to eachFolder
                exit repeat
            end if
        end repeat

        if targetFolder is missing value then
            set targetFolder to make new folder with properties {name:targetFolderName}
        end if

        make new note at targetFolder with properties {name:noteTitle, body:noteBody}
    end tell
end run
'''


class NotesWriter:
    """Create Notes entries using osascript."""

    def __init__(
        self,
        folder_name: str,
        append_index: bool = True,
        delay_seconds: float = 0.2,
        show_progress: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.folder_name = folder_name
        self.append_index = append_index
        self.delay_seconds = max(0.0, delay_seconds)
        self.show_progress = show_progress
        self.logger = logger or LOGGER
        self.failed_notes: list[str] = []

    def create_note(self, title: str, body: str) -> None:
        """Create a new note in the configured Notes folder."""
        html_body = self._to_notes_html(body)
        command = ["osascript", "-", title, html_body, self.folder_name]
        try:
            completed = subprocess.run(
                command,
                input=APPLE_SCRIPT,
                text=True,
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or exc.stdout or "").strip()
            lowered = message.lower()
            if "not authorized" in lowered or "权限" in message or "1743" in message:
                raise AppError(
                    "Notes 权限不足。请在“系统设置 > 隐私与安全性 > 自动化”中允许终端或 Python 控制 Notes。"
                ) from exc
            raise AppError(f"AppleScript 写入失败：{message or '未知错误'}") from exc

        if completed.stderr.strip():
            raise AppError(f"AppleScript 写入失败：{completed.stderr.strip()}")

    def write_paragraphs(self, paragraphs: list[str], base_title: str = "Note") -> dict[str, bool]:
        """Create one Apple Note per non-empty paragraph and return per-note status."""
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
            self.logger.info("没有可写入 Notes 的有效段落，已跳过。")
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
                self.logger.error("Apple Notes 写入失败：title=%s error=%s", title, exc)
            else:
                results[title] = True
                self.logger.info("Apple Notes 写入成功：title=%s", title)

            if self.delay_seconds > 0 and index < total:
                time.sleep(self.delay_seconds)

        return results

    def _build_note_title(self, base_title: str, index: int) -> str:
        """Build the final note title for a paragraph entry."""
        title = (base_title or "Note").strip() or "Note"
        if not self.append_index:
            return title
        return f"{title} {index}"

    @staticmethod
    def _to_notes_html(body: str) -> str:
        """Convert plain text into Notes-friendly HTML."""
        escaped = html.escape(body)
        return escaped.replace("\n", "<br>")
