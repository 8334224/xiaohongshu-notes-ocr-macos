"""Public no-login HTML fetcher for Xiaohongshu note pages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from utils import AppError
from xhs_url_validator import ParsedXhsUrl

SCRIPT_TAG_PATTERN = re.compile(r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
META_TAG_PATTERN = re.compile(
    r"<meta\b[^>]+(?:property|name)=[\"'](?P<name>[^\"']+)[\"'][^>]+content=[\"'](?P<content>[^\"']+)[\"'][^>]*>",
    re.IGNORECASE,
)
TITLE_TAG_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
IMAGE_URL_PATTERN = re.compile(
    r"https?:\\?/\\?/[^\"'<>\s]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\"'<>\s]*)?",
    re.IGNORECASE,
)
JSON_IMAGE_HINT_PATTERN = re.compile(r"(image|images|note|media|swiper|photo|pic|cover)", re.IGNORECASE)


@dataclass(frozen=True)
class PublicFetchResult:
    """Structured result of a no-login public note fetch."""

    final_url: str
    image_urls: list[str]
    title: Optional[str]
    author: Optional[str]
    extraction_method: Optional[str]
    html_path: Optional[str]


class XhsPublicFetcher:
    """Fetch a Xiaohongshu note page without cookies or browser automation."""

    def __init__(self, timeout_seconds: int = 15) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, parsed_url: ParsedXhsUrl, html_output_path: Path | str | None = None) -> PublicFetchResult:
        """Fetch a public note page and extract title, author, and image URLs."""
        html, final_url = self._fetch_html(parsed_url.canonical_url)
        saved_html_path = self._save_html_if_requested(html, html_output_path)

        title = self._extract_title(html)
        author = self._extract_author(html)
        image_urls, extraction_method = self._extract_image_urls(html)

        return PublicFetchResult(
            final_url=final_url,
            image_urls=image_urls,
            title=title,
            author=author,
            extraction_method=extraction_method,
            html_path=str(saved_html_path) if saved_html_path else None,
        )

    def _fetch_html(self, url: str) -> tuple[str, str]:
        """Fetch the raw HTML of a public note page."""
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = response.read()
                final_url = response.geturl()
                html = self._decode_html(data, response)
        except Exception as exc:
            raise AppError(f"公开页面抓取失败：{url}") from exc

        if not html.strip():
            raise AppError("公开页面抓取失败：返回 HTML 为空。")
        return html, final_url

    @staticmethod
    def _decode_html(data: bytes, response) -> str:
        """Decode HTML bytes using the response charset when available."""
        charset = None
        headers = getattr(response, "headers", None)
        if headers is not None and hasattr(headers, "get_content_charset"):
            charset = headers.get_content_charset()
        return data.decode(charset or "utf-8", errors="ignore")

    @staticmethod
    def _save_html_if_requested(html: str, html_output_path: Path | str | None) -> Path | None:
        """Persist fetched HTML only when the caller explicitly asks for it."""
        if html_output_path is None:
            return None

        path = Path(html_output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return path

    @staticmethod
    def _extract_title(html: str) -> Optional[str]:
        """Extract the note title from meta tags or title tag."""
        meta_values = XhsPublicFetcher._meta_map(html)
        for key in ("og:title", "twitter:title"):
            value = meta_values.get(key)
            if value:
                return XhsPublicFetcher._clean_title(value)

        match = TITLE_TAG_PATTERN.search(html)
        if not match:
            return None
        return XhsPublicFetcher._clean_title(XhsPublicFetcher._strip_html(match.group(1)))

    @staticmethod
    def _extract_author(html: str) -> Optional[str]:
        """Extract the author from meta tags or embedded JSON."""
        meta_values = XhsPublicFetcher._meta_map(html)
        for key in ("author", "og:article:author"):
            value = meta_values.get(key)
            if value:
                return value.strip() or None

        for field in ("author", "nickname", "userName", "username"):
            match = re.search(rf'"{field}"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
            if match:
                return XhsPublicFetcher._unescape_text(match.group(1)).strip() or None
        return None

    @staticmethod
    def _extract_image_urls(html: str) -> tuple[list[str], Optional[str]]:
        """Extract image URLs from HTML with a conservative method priority."""
        script_urls = XhsPublicFetcher._extract_image_urls_from_scripts(html)
        if script_urls:
            return script_urls, "embedded_json"

        meta_urls = XhsPublicFetcher._extract_image_urls_from_meta(html)
        if meta_urls:
            return meta_urls, "meta_tags"

        html_urls = XhsPublicFetcher._extract_image_urls_from_html(html)
        if html_urls:
            return html_urls, "html_regex"
        return [], None

    @staticmethod
    def _extract_image_urls_from_scripts(html: str) -> list[str]:
        """Choose the most likely正文图片序列 from embedded script content."""
        best_urls: list[str] = []
        best_score: tuple[int, int] | None = None

        for script in SCRIPT_TAG_PATTERN.findall(html):
            script_text = script.strip()
            if not script_text:
                continue

            urls = XhsPublicFetcher._extract_urls_from_text(script_text)
            if not urls:
                continue

            unique_urls = XhsPublicFetcher._dedupe_preserve_order(urls)
            if not unique_urls:
                continue

            score = (
                1 if JSON_IMAGE_HINT_PATTERN.search(script_text) else 0,
                len(unique_urls),
            )
            if best_score is None or score > best_score:
                best_score = score
                best_urls = unique_urls

            candidate_json = XhsPublicFetcher._try_parse_embedded_json(script_text)
            if candidate_json is not None:
                json_urls = XhsPublicFetcher._extract_urls_from_json(candidate_json)
                json_urls = XhsPublicFetcher._dedupe_preserve_order(json_urls)
                json_score = (
                    2 if json_urls else 0,
                    len(json_urls),
                )
                if json_urls and (best_score is None or json_score > best_score):
                    best_score = json_score
                    best_urls = json_urls

        return best_urls

    @staticmethod
    def _extract_image_urls_from_meta(html: str) -> list[str]:
        """Extract fallback images from og:image style meta tags."""
        meta_values = XhsPublicFetcher._meta_map(html)
        urls: list[str] = []
        for key in ("og:image", "twitter:image"):
            value = meta_values.get(key)
            if value:
                urls.append(value)
        return XhsPublicFetcher._dedupe_preserve_order(urls)

    @staticmethod
    def _extract_image_urls_from_html(html: str) -> list[str]:
        """Fallback to raw HTML URL scanning."""
        return XhsPublicFetcher._dedupe_preserve_order(XhsPublicFetcher._extract_urls_from_text(html))

    @staticmethod
    def _extract_urls_from_text(text: str) -> list[str]:
        """Extract and normalize image URLs from arbitrary text."""
        urls: list[str] = []
        for match in IMAGE_URL_PATTERN.findall(text):
            url = XhsPublicFetcher._normalize_image_url(match)
            if XhsPublicFetcher._keep_image_url(url):
                urls.append(url)
        return urls

    @staticmethod
    def _try_parse_embedded_json(script_text: str):
        """Try to parse embedded JSON or JS-assignment JSON."""
        candidates = [script_text]
        assign_match = re.search(r"=\s*(\{.*\}|\[.*\])\s*;?\s*$", script_text, re.DOTALL)
        if assign_match:
            candidates.append(assign_match.group(1))

        for candidate in candidates:
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    @staticmethod
    def _extract_urls_from_json(value) -> list[str]:
        """Recursively extract image-like URLs from parsed JSON structures."""
        urls: list[str] = []

        def visit(node, key_path: str = "") -> None:
            if node is None:
                return
            if isinstance(node, str):
                if IMAGE_URL_PATTERN.fullmatch(node) and JSON_IMAGE_HINT_PATTERN.search(key_path):
                    normalized = XhsPublicFetcher._normalize_image_url(node)
                    if XhsPublicFetcher._keep_image_url(normalized):
                        urls.append(normalized)
                return
            if isinstance(node, list):
                for item in node:
                    visit(item, key_path)
                return
            if isinstance(node, dict):
                for key, child in node.items():
                    visit(child, f"{key_path}.{key}" if key_path else str(key))

        visit(value)
        return urls

    @staticmethod
    def _meta_map(html: str) -> dict[str, str]:
        """Collect relevant meta tag contents into a name->content map."""
        meta_values: dict[str, str] = {}
        for match in META_TAG_PATTERN.finditer(html):
            meta_values[match.group("name").lower()] = XhsPublicFetcher._unescape_text(match.group("content"))
        return meta_values

    @staticmethod
    def _dedupe_preserve_order(urls: list[str]) -> list[str]:
        """Deduplicate image URLs while preserving order."""
        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            canonical = XhsPublicFetcher._canonicalize_image_url(url)
            if canonical in seen:
                continue
            seen.add(canonical)
            deduped.append(url)
        return deduped

    @staticmethod
    def _canonicalize_image_url(url: str) -> str:
        """Build a stable deduplication key for public image URLs."""
        parsed = urlparse(url)
        path = parsed.path
        if "!" in path:
            path = path.split("!", 1)[0]
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"

    @staticmethod
    def _normalize_image_url(url: str) -> str:
        """Normalize escaped or HTML-encoded image URLs."""
        return (
            url.replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("&amp;", "&")
            .split(" ")[0]
            .strip()
        )

    @staticmethod
    def _keep_image_url(url: str) -> bool:
        """Filter obviously non-body image URLs."""
        if not url.lower().startswith("http"):
            return False
        lowered = url.lower()
        if any(token in lowered for token in ("avatar", "profile", "logo")):
            return False
        return True

    @staticmethod
    def _clean_title(value: str) -> Optional[str]:
        """Normalize a note title from meta/title text."""
        cleaned = XhsPublicFetcher._unescape_text(value).strip()
        cleaned = re.sub(r"\s*-\s*小红书.*$", "", cleaned)
        return cleaned or None

    @staticmethod
    def _strip_html(value: str) -> str:
        """Strip simple HTML tags from text fragments."""
        return re.sub(r"<[^>]+>", "", value)

    @staticmethod
    def _unescape_text(value: str) -> str:
        """Unescape common HTML/JSON text encodings."""
        return (
            value.replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("&amp;", "&")
            .replace("&quot;", '"')
        )


def fetch_public_note(parsed_url: ParsedXhsUrl, html_output_path: Path | str | None = None) -> PublicFetchResult:
    """Convenience wrapper for a one-shot public note fetch."""
    return XhsPublicFetcher().fetch(parsed_url, html_output_path=html_output_path)
