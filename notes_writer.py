"""Apple Notes writer via AppleScript."""

from __future__ import annotations

import html
import subprocess

from utils import AppError

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

    def __init__(self, folder_name: str) -> None:
        self.folder_name = folder_name

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

    @staticmethod
    def _to_notes_html(body: str) -> str:
        """Convert plain text into Notes-friendly HTML."""
        escaped = html.escape(body)
        return escaped.replace("\n", "<br>")
