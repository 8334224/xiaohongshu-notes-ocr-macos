"""Clipboard helpers for reading Xiaohongshu URLs."""

from __future__ import annotations

import os
import subprocess

from utils import AppError


def read_clipboard_text() -> str:
    """Read plain text from the XHS_URL env var or the macOS system clipboard."""
    env_url = os.environ.get("XHS_URL", "").strip()
    if env_url:
        return env_url

    try:
        completed = subprocess.run(
            ["pbpaste"],
            text=True,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise AppError("当前环境不支持 pbpaste，无法读取 macOS 系统剪贴板。") from exc
    except subprocess.CalledProcessError as exc:
        raise AppError(f"读取剪贴板失败：{(exc.stderr or exc.stdout or '').strip() or '未知错误'}") from exc

    text = completed.stdout.strip()
    if not text:
        raise AppError("剪贴板为空，请先复制一条小红书笔记网页链接。")
    return text
