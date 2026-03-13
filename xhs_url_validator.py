"""Validation and normalization for supported Xiaohongshu note URLs."""

from __future__ import annotations

import re
from urllib.request import Request, urlopen
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from utils import AppError

URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
SUPPORTED_HOST_SUFFIXES = ("xiaohongshu.com",)
SHORT_LINK_HOST_SUFFIXES = ("xhslink.com",)
SUPPORTED_PATH_PREFIXES = (
    "/explore/",
    "/discovery/item/",
    "/discovery/note/",
)
PROFILE_NOTE_PATTERN = re.compile(r"^/user/profile/(?P<user_id>[^/]+)/(?P<note_id>[^/?#]+)$")


def validate_xhs_note_url(raw_text: str) -> str:
    """Validate and normalize a clipboard string as a supported Xiaohongshu note URL."""
    text = raw_text.strip()
    if not text:
        raise AppError("剪贴板为空，请先复制一条小红书笔记网页链接。")

    extracted_url = _extract_url_from_text(text)
    resolved_url = _resolve_short_url_if_needed(extracted_url)
    parsed = urlparse(resolved_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AppError("剪贴板内容不是合法 URL。")

    host = parsed.netloc.lower()
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in SUPPORTED_HOST_SUFFIXES):
        raise AppError("不是支持的小红书笔记网页链接。")

    if any(parsed.path.startswith(prefix) for prefix in SUPPORTED_PATH_PREFIXES):
        return _normalize_explore_url(parsed)

    match = PROFILE_NOTE_PATTERN.fullmatch(parsed.path)
    if match:
        return _normalize_profile_note_url(parsed, match.group("note_id"))

    raise AppError("不是支持的小红书图文笔记链接。")


def _normalize_explore_url(parsed) -> str:
    """Normalize a supported note URL to the canonical explore form when possible."""
    if parsed.path.startswith("/explore/"):
        return parsed.geturl()

    note_id = parsed.path.rstrip("/").split("/")[-1]
    return _build_explore_url(note_id, parsed)


def _normalize_profile_note_url(parsed, note_id: str) -> str:
    """Convert /user/profile/<user_id>/<note_id> URLs into canonical /explore/<note_id> URLs."""
    if not note_id:
        raise AppError("不是合法的小红书 profile 笔记链接。")
    return _build_explore_url(note_id, parsed)


def _build_explore_url(note_id: str, parsed) -> str:
    """Build a canonical explore URL while preserving the original query string."""
    query = urlencode(parse_qsl(parsed.query, keep_blank_values=True))
    return urlunparse((parsed.scheme, "www.xiaohongshu.com", f"/explore/{note_id}", "", query, ""))


def _extract_url_from_text(text: str) -> str:
    """Extract the first HTTP(S) URL from clipboard text."""
    match = URL_PATTERN.search(text)
    if not match:
        raise AppError("剪贴板内容不是合法 URL。")
    return match.group(0).rstrip("!！）)]}>\"'")


def _resolve_short_url_if_needed(url: str) -> str:
    """Resolve Xiaohongshu short links into their final note URLs."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in SHORT_LINK_HOST_SUFFIXES):
        return url

    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.geturl()
    except Exception as exc:
        raise AppError(f"小红书短链解析失败：{url}") from exc
