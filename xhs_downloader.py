"""Download Xiaohongshu note images with public fetch first and browser fallback."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import (
    DEFAULT_CHROME_CDP_URL,
    OCR_FOLDER,
    OCR_DEBUG_FOLDER,
    PLAYWRIGHT_TIMEOUT_MS,
    PLAYWRIGHT_WAIT_AFTER_LOAD_MS,
)
from downloader_utils import build_download_filename, cleanup_ocr_image_files, ensure_ocr_folder
from utils import AppError, clean_note_text, normalize_note_title
from xhs_public_fetcher import fetch_public_note
from xhs_url_validator import ParsedXhsUrl, parse_xhs_url

IMAGE_URL_PATTERN = re.compile(r"https?://[^\s\"']+\.(?:jpg|jpeg|png|webp)(?:\?[^\s\"']*)?", re.IGNORECASE)
UNTITLED_DOWNLOAD_TITLE = "无标题笔记"


@dataclass(frozen=True)
class ExtractedNote:
    """Structured data extracted from a Xiaohongshu note page."""

    title: str
    author: str
    display_title: str | None
    note_text: str | None
    note_type: str
    image_urls: list[str]


@dataclass(frozen=True)
class DownloadResult:
    """Downloaded image paths and the optional extracted note text."""

    paths: list[Path]
    note_title: str | None
    note_author: str | None
    note_text: str | None
    note_type: str


@dataclass(frozen=True)
class PageSignals:
    """Signals used to distinguish a note page from a login gate."""

    has_title: bool
    has_author: bool
    has_main_region: bool
    has_images: bool
    login_signal_count: int


@dataclass(frozen=True)
class ImageSelection:
    """Final chosen image source and its ordered image URLs."""

    source_type: str
    urls: list[str]
    raw_candidate_count: int


class XiaohongshuDownloader:
    """Open a Xiaohongshu note page and download its images."""

    def __init__(
        self,
        output_folder: Path | None = None,
        debug_folder: Path | None = None,
        use_local_chrome: bool = False,
        chrome_cdp_url: str = DEFAULT_CHROME_CDP_URL,
    ) -> None:
        self.output_folder = output_folder or OCR_FOLDER
        self.debug_folder = debug_folder or OCR_DEBUG_FOLDER
        self.use_local_chrome = use_local_chrome
        self.chrome_cdp_url = chrome_cdp_url

    def download_from_url(self, url: str) -> list[Path]:
        """Download note images into the OCR folder and return their paths."""
        return self.download_from_url_with_result(url).paths

    def download_from_url_with_result(self, url: str) -> DownloadResult:
        """Download note images and return both file paths and extracted note text."""
        return self.download_from_parsed_url_with_result(parse_xhs_url(url))

    def download_from_parsed_url(self, parsed_url: ParsedXhsUrl) -> list[Path]:
        """Download note images using public fetch first, then browser fallback."""
        return self.download_from_parsed_url_with_result(parsed_url).paths

    def download_from_parsed_url_with_result(self, parsed_url: ParsedXhsUrl) -> DownloadResult:
        """Download note images using public fetch first, then browser fallback."""
        self.output_folder.mkdir(parents=True, exist_ok=True)
        folder = self.output_folder
        removed = cleanup_ocr_image_files(folder)
        if removed:
            print(f"已清理 OCR 目录中的旧图片：{len(removed)} 张")

        note = self._extract_note_with_fallback(parsed_url)
        print(
            "提取结果："
            f"note_type={note.note_type}, "
            f"title={note.display_title or ''}, "
            f"author={note.author or ''}, "
            f"image_url_count={len(note.image_urls)}, "
            f"has_note_text={bool((note.note_text or '').strip())}"
        )
        print(f"准备按 {note.note_type} 模式处理")
        if note.note_type == "video":
            if note.image_urls:
                print("提示：检测到视频笔记，存在封面图 URL，但已跳过图片下载和 OCR。")
            print("提示：检测到纯视频笔记，已跳过图片下载和 OCR，仅提取正文内容。")
            return DownloadResult(
                paths=[],
                note_title=note.display_title,
                note_author=note.author,
                note_text=note.note_text,
                note_type=note.note_type,
            )
        if note.note_type == "unknown" and not note.image_urls:
            print("提示：笔记类型未明确，且未检测到图片组，已按正文优先处理。")
            return DownloadResult(
                paths=[],
                note_title=note.display_title,
                note_author=note.author,
                note_text=note.note_text,
                note_type=note.note_type,
            )
        if not note.image_urls:
            raise AppError("页面没有可下载的图片。")

        if note.note_type == "video":
            raise AppError("逻辑错误：video 分支不应进入图片下载。")

        downloaded_paths: list[Path] = []
        for index, image_url in enumerate(note.image_urls, start=1):
            filename = build_download_filename(note.title, note.author, index, image_url)
            target_path = folder / filename
            self._download_image(image_url, target_path, referer=parsed_url.canonical_url)
            downloaded_paths.append(target_path)

        print(f"最终下载数量：{len(downloaded_paths)}")

        if not downloaded_paths:
            raise AppError("下载后图片数量为 0，任务已终止。")

        return DownloadResult(
            paths=downloaded_paths,
            note_title=note.display_title,
            note_author=note.author,
            note_text=note.note_text,
            note_type=note.note_type,
        )

    def _extract_note_with_fallback(self, parsed_url: ParsedXhsUrl) -> ExtractedNote:
        """Try public no-login extraction first, then fall back to browser extraction."""
        public_debug_path = self.debug_folder / "public_fetch.html"
        public_debug_summary_path = self.debug_folder / "public_fetch_debug.txt"
        public_debug_json_path = self.debug_folder / "public_fetch_debug.json"
        fallback_strategy = self._fallback_strategy_name()
        print("抓取策略：public_fetch 优先")
        try:
            public_result = fetch_public_note(parsed_url, html_output_path=public_debug_path)
            print(
                "public_fetch 结果："
                f"final_url={public_result.final_url}, "
                f"method={public_result.extraction_method or 'none'}, "
                f"note_type={public_result.note_type}, "
                f"title={bool(public_result.title)}, "
                f"author={bool(public_result.author)}, "
                f"images={len(public_result.image_urls)}"
            )
            if public_result.html_path:
                print(f"公开抓取 HTML 已保存：{public_result.html_path}")

            is_usable, reasons = self._is_public_fetch_usable(public_result)
            strategy_used = "public_fetch" if is_usable else fallback_strategy
            self._write_public_fetch_debug(
                public_debug_summary_path,
                public_debug_json_path,
                parsed_url,
                public_result,
                reasons=reasons,
                download_strategy_used=strategy_used,
            )
            if is_usable:
                print(
                    "抓取策略：public_fetch 成功："
                    f"{len(public_result.image_urls)} 张图，method={public_result.extraction_method or 'unknown'}"
                )
                display_title = normalize_note_title(public_result.title, public_result.author)
                return ExtractedNote(
                    title=display_title or UNTITLED_DOWNLOAD_TITLE,
                    author=public_result.author,
                    display_title=display_title,
                    note_text=public_result.note_text,
                    note_type=public_result.note_type,
                    image_urls=public_result.image_urls,
                )

            raise AppError(f"公开抓取结果未通过质量判定：{'; '.join(reasons)}")
        except AppError as exc:
            if not public_debug_summary_path.exists():
                self._write_public_fetch_failure_debug(
                    public_debug_summary_path,
                    public_debug_json_path,
                    parsed_url,
                    str(exc),
                    download_strategy_used=fallback_strategy,
                )
            print(f"抓取策略：public_fetch 未成功：{exc}")
            print(f"公开抓取调试摘要：{public_debug_summary_path}")
            print(f"抓取策略：回退到 {fallback_strategy}")
            return self._extract_note(parsed_url.canonical_url)

    def _fallback_strategy_name(self) -> str:
        """Return the concrete browser fallback strategy name."""
        return "local_chrome" if self.use_local_chrome else "playwright"

    @staticmethod
    def _is_public_fetch_usable(public_result) -> tuple[bool, list[str]]:
        """Return whether a public fetch result is complete enough to skip browser fallback."""
        reasons: list[str] = []
        final_host = urlparse(public_result.final_url).netloc.lower()
        if not final_host.endswith("xiaohongshu.com"):
            reasons.append("final_url 不是小红书域名")
        if public_result.note_type == "video":
            if not public_result.note_text:
                reasons.append("视频笔记缺少正文")
            if not public_result.author:
                reasons.append("缺少作者")
            return not reasons, reasons
        if not public_result.title:
            reasons.append("缺少标题")
        elif public_result.title in {"小红书 - 你的生活兴趣社区", "安全限制"}:
            reasons.append("标题仍是通用站点标题")
        if not public_result.author:
            reasons.append("缺少作者")
        elif public_result.author in {"登录", "手机号登录", "获取验证码"}:
            reasons.append("作者字段命中了登录门槛文案")
        if not public_result.image_urls:
            reasons.append("没有抓到图片")
        if not public_result.extraction_method:
            reasons.append("没有提取来源标记")
        elif public_result.extraction_method == "meta_tags":
            reasons.append("仅抓到 meta 封面图，结果可信度不足")
        return not reasons, reasons

    def _write_public_fetch_debug(
        self,
        text_path: Path,
        json_path: Path,
        parsed_url: ParsedXhsUrl,
        public_result,
        reasons: list[str],
        download_strategy_used: str,
    ) -> None:
        """Write a small debug summary for the public fetch attempt."""
        try:
            self._ensure_debug_folder()
            debug_payload = {
                "original_input": parsed_url.original_input,
                "canonical_url": parsed_url.canonical_url,
                "final_url": public_result.final_url,
                "note_id": parsed_url.note_id,
                "xsec_token_present": bool(parsed_url.xsec_token),
                "xsec_source": parsed_url.xsec_source or "",
                "share_link_host": parsed_url.share_link_host or "",
                "title": public_result.title or "",
                "author": public_result.author or "",
                "note_type": public_result.note_type,
                "image_count": len(public_result.image_urls),
                "extraction_method": public_result.extraction_method or "",
                "html_path": public_result.html_path or "",
                "quality_ok": not reasons,
                "quality_reason": "; ".join(reasons),
                "download_strategy_used": download_strategy_used,
            }
            lines = [
                f"original_input: {debug_payload['original_input']}",
                f"canonical_url: {debug_payload['canonical_url']}",
                f"final_url: {debug_payload['final_url']}",
                f"note_id: {debug_payload['note_id']}",
                f"xsec_token_present: {str(debug_payload['xsec_token_present']).lower()}",
                f"xsec_source: {debug_payload['xsec_source']}",
                f"share_link_host: {debug_payload['share_link_host']}",
                f"title: {debug_payload['title']}",
                f"author: {debug_payload['author']}",
                f"note_type: {debug_payload['note_type']}",
                f"image_count: {debug_payload['image_count']}",
                f"extraction_method: {debug_payload['extraction_method']}",
                f"html_path: {debug_payload['html_path']}",
                f"quality_ok: {str(debug_payload['quality_ok']).lower()}",
                f"quality_reason: {debug_payload['quality_reason']}",
                f"download_strategy_used: {debug_payload['download_strategy_used']}",
            ]
            text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            json_path.write_text(json.dumps(debug_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:  # pragma: no cover
            return

    def _write_public_fetch_failure_debug(
        self,
        text_path: Path,
        json_path: Path,
        parsed_url: ParsedXhsUrl,
        error_message: str,
        download_strategy_used: str,
    ) -> None:
        """Write a debug summary when public fetching fails before producing a result."""
        try:
            self._ensure_debug_folder()
            debug_payload = {
                "original_input": parsed_url.original_input,
                "canonical_url": parsed_url.canonical_url,
                "final_url": "",
                "note_id": parsed_url.note_id,
                "xsec_token_present": bool(parsed_url.xsec_token),
                "xsec_source": parsed_url.xsec_source or "",
                "share_link_host": parsed_url.share_link_host or "",
                "title": "",
                "author": "",
                "note_type": "",
                "image_count": 0,
                "extraction_method": "",
                "html_path": "",
                "quality_ok": False,
                "quality_reason": error_message,
                "download_strategy_used": download_strategy_used,
            }
            lines = [
                f"original_input: {debug_payload['original_input']}",
                f"canonical_url: {debug_payload['canonical_url']}",
                f"final_url: {debug_payload['final_url']}",
                f"note_id: {debug_payload['note_id']}",
                f"xsec_token_present: {str(debug_payload['xsec_token_present']).lower()}",
                f"xsec_source: {debug_payload['xsec_source']}",
                f"share_link_host: {debug_payload['share_link_host']}",
                f"title: {debug_payload['title']}",
                f"author: {debug_payload['author']}",
                f"note_type: {debug_payload['note_type']}",
                f"image_count: {debug_payload['image_count']}",
                f"extraction_method: {debug_payload['extraction_method']}",
                f"html_path: {debug_payload['html_path']}",
                f"quality_ok: {str(debug_payload['quality_ok']).lower()}",
                f"quality_reason: {debug_payload['quality_reason']}",
                f"download_strategy_used: {debug_payload['download_strategy_used']}",
            ]
            text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            json_path.write_text(json.dumps(debug_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:  # pragma: no cover
            return

    def _extract_note(self, url: str) -> ExtractedNote:
        """Use Playwright to extract title, author and image URLs from a note page."""
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise AppError(
                "Playwright 未安装。请先执行 `pip install -r requirements.txt` 和 `playwright install chromium`。"
            ) from exc

        try:
            with sync_playwright() as playwright:
                browser, page, should_close_browser, browser_mode = self._open_browser_page(playwright, url)
                html = ""
                page_text = ""
                note_type = "unknown"
                try:
                    print("提示：已创建页面对象")
                    print("提示：开始打开目标页面")
                    if page.url != url:
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT_MS)
                        except PlaywrightTimeoutError as exc:
                            raise AppError("页面已创建，但打开目标链接失败：超时。") from exc
                        except PlaywrightError as exc:
                            raise AppError(f"页面已创建，但打开目标链接失败：{exc}") from exc
                    print("提示：页面打开成功，开始提取内容")
                    page.wait_for_timeout(PLAYWRIGHT_WAIT_AFTER_LOAD_MS)
                    self._scroll_page(page)
                    page.wait_for_timeout(500)
                    try:
                        extracted = page.evaluate(EXTRACTION_SCRIPT)
                        html = page.content()
                        page_text = page.locator("body").inner_text(timeout=5000)
                    except PlaywrightTimeoutError as exc:
                        raise AppError("页面已打开，但正文提取脚本执行失败：超时。") from exc
                    except PlaywrightError as exc:
                        raise AppError(f"页面已打开，但正文提取脚本执行失败：{exc}") from exc
                    print(f"信号判定前 page.url：{page.url}")
                    print(f"信号判定前 page_text 长度：{len(page_text)}")
                    print(f"信号判定前是否成功拿到 HTML：{bool(html)}")
                    screenshot_ok = self._save_debug_screenshot(page)
                    print(f"信号判定前是否成功拿到 screenshot：{screenshot_ok}")
                    signals = self._build_page_signals(extracted, html, page_text)
                    self._print_signal_debug(page, signals)

                    error_message = self._classify_page_failure(signals, html, page_text)
                    if error_message:
                        self._save_debug_artifacts(page, html)
                        raise AppError(error_message)

                    author = str(extracted.get("author", "")).strip() or self._extract_author_from_html(html)
                    if not author:
                        self._save_debug_artifacts(page, html)
                        raise AppError("页面提取作者失败。")
                    title = normalize_note_title(str(extracted.get("title", "")).strip(), author)

                    image_candidates = self._collect_image_candidates(extracted, html)
                    image_selection = self._select_image_source(image_candidates, verbose=True)
                    print(f"页面检测到正文图片数量：{len(image_selection.urls)}")
                    print(f"原始候选数量：{image_selection.raw_candidate_count}")
                    print(f"采用来源：{image_selection.source_type}")
                    if image_selection.source_type == "generic_img":
                        print("使用了低可信度兜底提取：generic_img")
                    note_type = self._detect_note_type(extracted, html, image_selection.urls)
                    if note_type == "image":
                        pager_text = self._extract_pager_text(html)
                        if pager_text:
                            print(f"提示：检测到多图图文笔记（{pager_text}），按 image 模式处理。")
                    image_urls = image_selection.urls
                    if not image_urls and note_type != "video":
                        self._save_debug_artifacts(page, html)
                        raise AppError("页面没有图片，或当前版本未抓到图文图片。")
                except AppError:
                    raise
                except Exception:
                    self._save_debug_artifacts(page, html)
                    raise
                finally:
                    if should_close_browser:
                        browser.close()
        except PlaywrightTimeoutError as exc:
            raise AppError("页面打开超时，请确认链接可访问，或稍后重试。") from exc
        except PlaywrightError as exc:
            message = str(exc)
            if "Executable doesn't exist" in message:
                raise AppError("Playwright 浏览器未安装。请执行 `playwright install chromium`。") from exc
            raise AppError(f"浏览器初始化失败：{message}") from exc

        note_text = self._extract_note_text(extracted, title or "")
        return ExtractedNote(
            title=title or UNTITLED_DOWNLOAD_TITLE,
            author=author,
            display_title=title,
            note_text=note_text,
            note_type=note_type,
            image_urls=image_urls,
        )

    @staticmethod
    def _extract_author_from_html(html: str) -> str:
        """Extract author conservatively from HTML when DOM extraction misses it."""
        meta_match = re.search(
            r'<meta\b[^>]+(?:property|name)=["\'](?:author|og:article:author)["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if meta_match:
            return meta_match.group(1).strip()

        link_match = re.search(
            r'<a[^>]+href=["\'][^"\']*/user/profile/[^"\']+["\'][^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if link_match:
            linked_author = re.sub(r"<[^>]+>", "", link_match.group(1)).strip()
            if linked_author:
                return linked_author

        for field in ("author", "nickname", "nickName", "displayName", "userName", "username", "name"):
            match = re.search(rf'"{field}"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
            if match:
                value = match.group(1).replace("\\u002F", "/").strip()
                if value:
                    return value
        return ""

    @staticmethod
    def _extract_note_text(extracted: dict[str, object], title: str) -> str | None:
        """Extract note text conservatively without breaking the image OCR flow."""
        raw_note_text = str(extracted.get("noteText", "")).strip()
        if not raw_note_text:
            return None
        try:
            cleaned = clean_note_text(raw_note_text, title)
        except Exception:
            return None
        return cleaned or None

    @staticmethod
    def _detect_note_type(extracted: dict[str, object], html: str, image_urls: list[str]) -> str:
        """Detect whether the note is an image post, video post, or unknown."""
        extracted_note_type = str(extracted.get("noteType", "")).strip().lower()
        has_image_group_signal = XiaohongshuDownloader._has_image_group_signal(html, image_urls)
        has_video_signal = XiaohongshuDownloader._has_video_signal(extracted, html)
        if has_video_signal and len(image_urls) <= 1 and extracted_note_type != "image":
            return "video"
        if extracted_note_type == "video" and not has_image_group_signal:
            return "video"
        if has_video_signal and not has_image_group_signal:
            return "video"
        if extracted_note_type == "image" and has_image_group_signal:
            return "image"
        if has_image_group_signal:
            return "image"
        if has_video_signal and len(image_urls) <= 1:
            return "video"
        return "unknown"

    @staticmethod
    def _has_image_group_signal(html: str, image_urls: list[str]) -> bool:
        """Return whether the note has strong image-gallery signals."""
        if len(image_urls) >= 2:
            return True
        pager_match = re.search(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)", html)
        if pager_match and int(pager_match.group(2)) > 1 and len(image_urls) >= 2:
            return True
        return False

    @staticmethod
    def _has_video_signal(extracted: dict[str, object], html: str) -> bool:
        """Return whether the current note has strong video-note signals."""
        if str(extracted.get("noteType", "")).strip().lower() == "video":
            return True
        if re.search(r"<video\b", html, re.IGNORECASE):
            return True
        if re.search(r'"(?:noteType|postType)"\s*:\s*"video"', html, re.IGNORECASE):
            return True
        if re.search(r'"videoInfo"\s*:\s*\{[^}]*"(?:masterUrl|h264Url|media)"', html, re.IGNORECASE):
            return True
        if re.search(r'"(?:videoUrl|masterUrl|h264Url)"\s*:\s*"https?://', html, re.IGNORECASE):
            return True
        return False

    @staticmethod
    def _extract_pager_text(html: str) -> str | None:
        """Extract a visible image pager like 1/13 for debug logging."""
        match = re.search(r"(?<!\d)(\d{1,2}\s*/\s*\d{1,2})(?!\d)", html)
        return match.group(1).replace(" ", "") if match else None

    def _open_browser_page(self, playwright, target_url: str):
        """Open a page either in Playwright Chromium or in a local Chrome CDP session."""
        if self.use_local_chrome:
            print(f"提示：尝试连接本机 Chrome CDP 端口 {self.chrome_cdp_url}")
            try:
                return self._open_local_chrome_page(playwright, target_url)
            except AppError as exc:
                print(f"提示：CDP 连接失败，回退为自动启动浏览器。原因：{exc}")
                try:
                    browser, page, should_close_browser = self._launch_browser_page(playwright, headless=False)
                except AppError as fallback_exc:
                    if str(fallback_exc).startswith("自动启动浏览器失败"):
                        raise AppError("无法连接本机 Chrome 远程调试端口，且自动启动浏览器失败。") from fallback_exc
                    raise
                print("提示：自动启动浏览器成功")
                return browser, page, should_close_browser, "playwright_fallback"

        browser, page, should_close_browser = self._launch_browser_page(playwright, headless=True)
        return browser, page, should_close_browser, "playwright"

    def _launch_browser_page(self, playwright, headless: bool):
        """Launch a Playwright browser and create a usable page."""
        try:
            browser = playwright.chromium.launch(headless=headless)
        except Exception as exc:
            raise AppError(f"自动启动浏览器失败：{exc}") from exc
        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
            )
        except Exception as exc:
            try:
                browser.close()
            except Exception:
                pass
            raise AppError("已启动浏览器，但创建上下文失败。") from exc
        try:
            page = context.new_page()
        except Exception as exc:
            try:
                browser.close()
            except Exception:
                pass
            raise AppError("自动启动浏览器成功，但未能获取可用 page。") from exc
        return browser, page, True

    def _open_local_chrome_page(self, playwright, target_url: str):
        """Connect to a local Chrome CDP instance and reuse an existing page when possible."""
        try:
            browser = playwright.chromium.connect_over_cdp(self.chrome_cdp_url)
        except Exception as exc:
            raise AppError(f"无法连接本机 Chrome 远程调试端口：{exc}") from exc
        contexts = browser.contexts
        print(f"已连接后获取到 {len(contexts)} 个 browser contexts")
        if not contexts:
            raise AppError("已连接本机 Chrome，但没有可用的浏览器上下文。")

        selected_context = None
        selected_page = None
        target_host = urlparse(target_url).netloc.lower()
        target_path = urlparse(target_url).path

        for context_index, context in enumerate(contexts, start=1):
            pages = context.pages
            print(f"context[{context_index}] 中有 {len(pages)} 个 pages")
            for page_index, page in enumerate(pages, start=1):
                print(f"  page[{page_index}] URL: {page.url}")
                page_url = page.url.lower()
                if target_host in page_url and target_path in page.url:
                    selected_context = context
                    selected_page = page
                    break
                if selected_context is None and target_host in page_url:
                    selected_context = context
                    selected_page = page
            if selected_page is not None:
                break

        if selected_page is None:
            selected_context = contexts[0]
            try:
                selected_page = selected_context.new_page()
            except Exception as exc:
                raise AppError("已连接本机 Chrome，但未能创建页面对象。") from exc
            print("已有 pages 中未找到目标小红书页面，已在现有 context 中新开 page。")

        if selected_page is None:
            raise AppError("浏览器已启动，但未能获取页面对象。")

        print(f"最终选中的 page URL：{selected_page.url or 'about:blank'}")
        return browser, selected_page, False, "local_chrome"

    @staticmethod
    def _scroll_page(page) -> None:
        """Scroll the page to encourage lazy-loaded images to appear."""
        page.evaluate(
            """
            async () => {
              const step = 800;
              for (let i = 0; i < 5; i += 1) {
                window.scrollBy(0, step);
                await new Promise((resolve) => setTimeout(resolve, 250));
              }
              window.scrollTo(0, 0);
            }
            """
        )

    @staticmethod
    def _build_page_signals(extracted: dict[str, object], html: str, page_text: str) -> PageSignals:
        """Build note-page and login-page signals for classification."""
        title = str(extracted.get("title", "")).strip()
        author = str(extracted.get("author", "")).strip()
        image_candidates = XiaohongshuDownloader._collect_image_candidates(extracted, html)
        image_selection = XiaohongshuDownloader._select_image_source(image_candidates, verbose=False)
        combined = f"{html}\n{page_text}"

        return PageSignals(
            has_title=bool(title and title != "小红书 - 你的生活兴趣社区" and title != "安全限制"),
            has_author=bool(author),
            has_main_region=any(
                token in html
                for token in ("note-content", "note-container", "data-testid=\"note-page\"", "<article", "swiper-slide")
            ),
            has_images=bool(image_selection.urls),
            login_signal_count=sum(
                1
                for keyword in (
                    "登录后查看更多",
                    "登录后推荐更懂你的笔记",
                    "请先登录",
                    "扫码登录",
                    "手机号登录",
                    "获取验证码",
                )
                if keyword in combined
            ),
        )

    def _classify_page_failure(self, signals: PageSignals, html: str, page_text: str) -> str | None:
        """Classify a loaded page before field-level extraction errors are raised."""
        block_reason = self._detect_block_reason(html, page_text)
        if block_reason:
            return block_reason

        content_signal_count = sum(
            1 for present in (signals.has_title, signals.has_author, signals.has_main_region, signals.has_images) if present
        )
        if content_signal_count < 2 and signals.login_signal_count >= 2:
            if self.use_local_chrome:
                return "已连接本机 Chrome，但页面仍然要求登录或未进入正文页。"
            return "页面可能需要登录，当前版本请先确认该笔记可在未登录状态下访问。"
        return None

    @staticmethod
    def _detect_block_reason(html: str, page_text: str) -> str | None:
        """Detect common Xiaohongshu risk-control pages."""
        combined = f"{html}\n{page_text}"
        if any(keyword in combined for keyword in ("安全限制", "IP存在风险", "返回首页(2s)", "300012")):
            return "页面被小红书安全限制拦截（例如 300012 / IP存在风险），未进入笔记正文。"
        return None

    @staticmethod
    def _print_signal_debug(page, signals: PageSignals) -> None:
        """Print page classification signals for debugging."""
        print(f"当前 page URL：{page.url}")
        print(
            "正文信号："
            f"title={signals.has_title}, author={signals.has_author}, "
            f"main_region={signals.has_main_region}, images={signals.has_images}"
        )
        print(f"是否命中“正文信号”：{any((signals.has_title, signals.has_author, signals.has_main_region, signals.has_images))}")
        print(f"是否命中“登录信号”：{signals.login_signal_count > 0}（count={signals.login_signal_count}）")

    def _save_debug_artifacts(self, page, html: str) -> None:
        """Save the current page screenshot and HTML for failed live debugging."""
        debug_folder = self._ensure_debug_folder()
        debug_png = debug_folder / "debug_xhs_page.png"
        debug_html = debug_folder / "debug_xhs_page.html"
        try:
            self._save_debug_screenshot(page)
            debug_html.write_text(html, encoding="utf-8")
            print(f"已保存调试截图：{debug_png}")
            print(f"已保存调试 HTML：{debug_html}")
        except Exception as exc:  # pragma: no cover
            print(f"保存调试现场失败：{exc}")

    def _save_debug_screenshot(self, page) -> bool:
        """Save the current page screenshot and return whether it succeeded."""
        debug_png = self._ensure_debug_folder() / "debug_xhs_page.png"
        try:
            page.screenshot(path=str(debug_png), full_page=True)
            return True
        except Exception:  # pragma: no cover
            return False

    @staticmethod
    def _collect_image_candidates(extracted: dict[str, object], html: str) -> list[dict[str, str]]:
        """Collect image candidates with source metadata."""
        candidates: list[dict[str, str]] = []
        raw_candidates = extracted.get("imageCandidates", [])
        if isinstance(raw_candidates, list):
            for index, candidate in enumerate(raw_candidates, start=1):
                if not isinstance(candidate, dict):
                    continue
                url = str(candidate.get("url", "")).strip()
                if not url:
                    continue
                candidates.append(
                    {
                        "url": url,
                        "source_type": str(candidate.get("sourceType", "generic_img")).strip() or "generic_img",
                        "dom_context": str(candidate.get("domContext", "")).strip(),
                        "sequence": str(candidate.get("sequence", index)),
                    }
                )
        if not candidates:
            for index, url in enumerate(IMAGE_URL_PATTERN.findall(html), start=1):
                candidates.append(
                    {
                        "url": url,
                        "source_type": "generic_img",
                        "dom_context": "html_regex_fallback",
                        "sequence": str(index),
                    }
                )
        return candidates

    @staticmethod
    def _select_image_source(candidates: list[dict[str, str]], verbose: bool = False) -> ImageSelection:
        """Choose a single trusted candidate source and keep its ordered unique images."""
        source_priority = ["embedded_data", "main_carousel", "main_content", "generic_img"]
        per_source_candidates: dict[str, list[dict[str, str]]] = {source: [] for source in source_priority}
        per_source_urls: dict[str, list[str]] = {source: [] for source in source_priority}
        seen_per_source: dict[str, set[str]] = {source: set() for source in source_priority}
        raw_candidate_count = len(candidates)

        for index, candidate in enumerate(candidates, start=1):
            url = candidate.get("url", "").strip()
            source_type = candidate.get("source_type", "generic_img")
            dom_context = candidate.get("dom_context", "")
            filter_reason = XiaohongshuDownloader._filter_candidate_reason(url, source_type, dom_context)
            kept = False

            if not filter_reason:
                normalized = XiaohongshuDownloader._normalize_image_url(url)
                canonical = XiaohongshuDownloader._canonicalize_image_url(normalized)
                if source_type not in per_source_candidates:
                    source_type = "generic_img"
                if canonical in seen_per_source[source_type]:
                    filter_reason = "duplicate_in_source"
                else:
                    kept = True
                    seen_per_source[source_type].add(canonical)
                    kept_candidate = dict(candidate)
                    kept_candidate["url"] = normalized
                    kept_candidate["canonical"] = canonical
                    per_source_candidates[source_type].append(kept_candidate)
                    per_source_urls[source_type].append(normalized)

            if verbose:
                print(
                    f"候选图[{index}] source={source_type} kept={kept} "
                    f"reason={filter_reason or 'kept'} url={url} dom={dom_context}"
                )

        for source in source_priority:
            if source == "main_carousel" and per_source_candidates[source]:
                assembled = XiaohongshuDownloader._assemble_main_carousel(
                    per_source_candidates[source],
                    verbose=verbose,
                )
                if assembled:
                    return ImageSelection(source_type=source, urls=assembled, raw_candidate_count=raw_candidate_count)
            elif per_source_urls[source]:
                return ImageSelection(source_type=source, urls=per_source_urls[source], raw_candidate_count=raw_candidate_count)
        return ImageSelection(source_type="none", urls=[], raw_candidate_count=raw_candidate_count)

    @staticmethod
    def _assemble_main_carousel(candidates: list[dict[str, str]], verbose: bool = False) -> list[str]:
        """Assemble carousel images, restoring unique images that only appear in clone nodes."""
        normal: list[dict[str, str]] = []
        clone_only: list[dict[str, str]] = []
        normal_canonicals: set[str] = set()
        all_unique_canonicals: list[str] = []
        seen_all: set[str] = set()

        for candidate in candidates:
            canonical = candidate["canonical"]
            if canonical not in seen_all:
                seen_all.add(canonical)
                all_unique_canonicals.append(canonical)

            if XiaohongshuDownloader._is_clone_context(candidate.get("dom_context", "")):
                clone_only.append(candidate)
                continue

            if canonical not in normal_canonicals:
                normal_canonicals.add(canonical)
                normal.append(candidate)

        clone_unique = [candidate for candidate in clone_only if candidate["canonical"] not in normal_canonicals]
        expected_count = len(all_unique_canonicals)

        if verbose:
            print(f"main_carousel 正常图数量：{len(normal)}")
            print(f"main_carousel clone-only 唯一图数量：{len(clone_unique)}")
            print(f"页面预期正文图数量：{expected_count}")

        assembled = [candidate["url"] for candidate in normal]
        if not clone_unique:
            if verbose:
                print(f"最终补齐后的数量：{len(assembled)}")
            return assembled

        normal_sequences = [int(candidate.get("sequence", "0")) for candidate in normal if str(candidate.get("sequence", "0")).isdigit()]
        first_normal_sequence = min(normal_sequences) if normal_sequences else None
        last_normal_sequence = max(normal_sequences) if normal_sequences else None

        prepend: list[str] = []
        append: list[str] = []
        for candidate in clone_unique:
            dom_context = candidate.get("dom_context", "").lower()
            sequence_text = str(candidate.get("sequence", "0"))
            sequence = int(sequence_text) if sequence_text.isdigit() else 0
            url = candidate["url"]
            reason = "clone_other_append"

            if "duplicate-prev" in dom_context:
                if first_normal_sequence is not None and sequence < first_normal_sequence:
                    append.append(url)
                    reason = "duplicate-prev_wraparound_to_end"
                else:
                    prepend.append(url)
                    reason = "duplicate-prev_front_fill"
            elif "duplicate-next" in dom_context:
                if last_normal_sequence is not None and sequence > last_normal_sequence:
                    prepend.insert(0, url)
                    reason = "duplicate-next_wraparound_to_front"
                else:
                    append.append(url)
                    reason = "duplicate-next_end_fill"
            else:
                append.append(url)

            if verbose:
                print(f"已补回 clone-only 缺失图：{url}，插入原因：{reason}")

        assembled = prepend + assembled + append
        if expected_count and len(assembled) > expected_count:
            assembled = assembled[:expected_count]
        if verbose:
            print(f"最终补齐后的数量：{len(assembled)}")
        return assembled

    @staticmethod
    def _is_clone_context(dom_context: str) -> bool:
        """Return whether a carousel candidate comes from a cloned/duplicated slide."""
        lowered = dom_context.lower()
        return any(token in lowered for token in ("duplicate", "cloned", "clone", "swiper-slide-duplicate"))

    @staticmethod
    def _filter_candidate_reason(url: str, source_type: str, dom_context: str) -> str | None:
        """Return a filter reason for candidates that should not be considered正文图片."""
        normalized = XiaohongshuDownloader._normalize_image_url(url)
        lowered_url = normalized.lower()
        lowered_context = dom_context.lower()
        if not normalized.startswith("http"):
            return "non_http"
        if source_type in {"avatar", "recommend", "comment", "thumbnail"}:
            return f"filtered_source:{source_type}"
        if "avatar" in lowered_url or "profile" in lowered_url:
            return "avatar_like_url"
        if "picasso-static.xiaohongshu.com" in lowered_url or "fe-platform" in lowered_url:
            return "emoji_or_ui_asset"
        if any(token in lowered_context for token in ("note-content-emoji", "emoji", "icon | inner")):
            return "emoji_or_ui_asset"
        if source_type != "main_carousel" and any(
            token in lowered_context for token in ("duplicate", "cloned", "clone", "swiper-slide-duplicate")
        ):
            return "carousel_clone"
        if any(token in lowered_context for token in ("recommend", "related", "comment", "avatar", "profile", "thumbnail", "thumb")):
            return "non_body_region"
        return None

    @staticmethod
    def _normalize_image_url(url: str) -> str:
        """Normalize a candidate image URL before filtering or deduplication."""
        return url.replace("\\u002F", "/").replace("&amp;", "&").split(" ")[0].strip()

    @staticmethod
    def _normalize_image_urls(urls: list[str]) -> list[str]:
        """Normalize a raw URL list and deduplicate it with generic_img rules."""
        candidates = [
            {"url": url, "source_type": "generic_img", "dom_context": "normalize_only", "sequence": str(index)}
            for index, url in enumerate(urls, start=1)
        ]
        return XiaohongshuDownloader._select_image_source(candidates).urls

    @staticmethod
    def _canonicalize_image_url(url: str) -> str:
        """Build a stable deduplication key for image URLs."""
        parsed = urlparse(url)
        path = parsed.path
        if "!" in path:
            path = path.split("!", 1)[0]
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"

    def _ensure_debug_folder(self) -> Path:
        """Ensure the debug artifact folder exists."""
        self.debug_folder.mkdir(parents=True, exist_ok=True)
        return self.debug_folder

    @staticmethod
    def _download_image(image_url: str, target_path: Path, referer: str) -> None:
        """Download a single image to disk."""
        request = Request(
            image_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Referer": referer,
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                data = response.read()
        except Exception as exc:  # pragma: no cover
            raise AppError(f"图片下载失败：{image_url}") from exc

        if not data:
            raise AppError(f"图片下载失败：{image_url}")
        target_path.write_bytes(data)


EXTRACTION_SCRIPT = r"""
() => {
  const textFromSelectors = (selectors) => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const value = node?.content || node?.innerText || node?.textContent || "";
      const cleaned = String(value).trim();
      if (cleaned) return cleaned;
    }
    return "";
  };

  const imageCandidates = [];
  let sequence = 0;
  const pushCandidate = (raw, sourceType, domContext) => {
    if (!raw) return;
    const value = String(raw).trim();
    if (!value || value.startsWith("data:")) return;
    sequence += 1;
    imageCandidates.push({
      url: value.split(" ")[0],
      sourceType,
      domContext,
      sequence,
    });
  };

  const buildDomContext = (el) => {
    if (!el) return "";
    const cls = String(el.className || "");
    const parentCls = String(el.parentElement?.className || "");
    const carouselCls = String(el.closest('[class*="swiper"], [class*="carousel"]')?.className || "");
    const ariaHidden = el.closest('[aria-hidden="true"]') ? "aria-hidden" : "";
    return [cls, parentCls, carouselCls, ariaHidden].filter(Boolean).join(" | ");
  };

  const extractUrlsFromValue = (value) => {
    const urls = [];
    const visit = (node) => {
      if (!node) return;
      if (typeof node === "string") {
        if (/^https?:\/\/.+\.(jpg|jpeg|png|webp)(\?|$)/i.test(node)) urls.push(node);
        return;
      }
      if (Array.isArray(node)) {
        node.forEach(visit);
        return;
      }
      if (typeof node === "object") {
        for (const [key, child] of Object.entries(node)) {
          if (/url|image|photo|pic|cover/i.test(key)) visit(child);
        }
      }
    };
    visit(value);
    return urls;
  };

  const tryCollectEmbeddedData = () => {
    const roots = [];
    for (const key of ["__INITIAL_STATE__", "__INITIAL_SSR_STATE__", "__SSR_DATA__", "__NEXT_DATA__", "__REDUX_STATE__"]) {
      if (window[key]) roots.push({ path: key, value: window[key] });
    }
    for (const script of document.querySelectorAll('script:not([src])')) {
      const text = (script.textContent || "").trim();
      if (!text || !/(image|images|note|media|swiper|photo|pic|cover)/i.test(text)) continue;
      if (!(text.startsWith("{") || text.startsWith("["))) continue;
      try {
        roots.push({ path: "script_json", value: JSON.parse(text) });
      } catch (_) {
      }
    }

    const walk = (value, path, depth) => {
      if (!value || depth > 8) return;
      if (Array.isArray(value)) {
        if (/(image|images|note|media|swiper|photo|pic|cover)/i.test(path)) {
          const urls = extractUrlsFromValue(value);
          urls.forEach((url, index) => pushCandidate(url, "embedded_data", `${path}[${index}]`));
        }
        value.forEach((item, index) => walk(item, `${path}[${index}]`, depth + 1));
        return;
      }
      if (typeof value === "object") {
        for (const [key, child] of Object.entries(value)) {
          walk(child, `${path}.${key}`, depth + 1);
        }
      }
    };

    roots.forEach((root) => walk(root.value, root.path, 0));
  };

  tryCollectEmbeddedData();

  const imageSelectors = [
    { selector: '.swiper-slide img, [class*="swiper"] img, [class*="carousel"] img', sourceType: 'main_carousel' },
    { selector: 'article img, main img, [data-testid="note-page"] img, .note-content img', sourceType: 'main_content' },
    { selector: 'img', sourceType: 'generic_img' },
  ];

  for (const entry of imageSelectors) {
    for (const img of document.querySelectorAll(entry.selector)) {
      let sourceType = entry.sourceType;
      const context = buildDomContext(img);
      const lowered = context.toLowerCase();
      if (/avatar|profile|author/.test(lowered)) sourceType = "avatar";
      else if (/recommend|related/.test(lowered)) sourceType = "recommend";
      else if (/comment/.test(lowered)) sourceType = "comment";
      else if (/thumb|thumbnail|indicator|dots|nav/.test(lowered)) sourceType = "thumbnail";

      pushCandidate(img.currentSrc || img.src, sourceType, context);
      const srcset = img.getAttribute("srcset") || "";
      for (const part of srcset.split(",")) {
        pushCandidate(part.trim(), sourceType, `${context} | srcset`);
      }
    }
  }

  for (const node of document.querySelectorAll('meta[property="og:image"], meta[name="og:image"]')) {
    pushCandidate(node.content, "generic_img", "meta:og:image");
  }

  const title = textFromSelectors([
    'meta[property="og:title"]',
    'meta[name="og:title"]',
    'meta[name="twitter:title"]',
    'h1',
    'title',
  ]).replace(/\s*-\s*小红书.*$/, "");

  const author = textFromSelectors([
    '[data-testid="note-page"] a[href*="/user/profile/"]',
    'main a[href*="/user/profile/"]',
    'article a[href*="/user/profile/"]',
    'meta[name="author"]',
    '[class*="author"] [class*="name"]',
    '[class*="author"]',
    '[class*="user"] [class*="name"]',
    'a[href*="/user/profile/"] span',
    'a[href*="/user/profile/"]',
  ]).replace(/^作者[:：]?\s*/, "");

  const noteText = textFromSelectors([
    '[data-testid="note-page"] [class*="content"]',
    '[data-testid="note-page"] article',
    '.note-content',
    '.note-text',
    'article [class*="desc"]',
    'article',
    'meta[name="description"]',
    'meta[property="og:description"]',
    'meta[name="twitter:description"]',
  ]).replace(/\s*-\s*小红书.*$/, "");

  const noteType = (() => {
    const hasImageGroupSignal = imageCandidates.length >= 2;
    if (hasImageGroupSignal) return "image";
    if (document.querySelector('video, [class*="video-player"], [data-testid*="video"]')) return "video";
    return "unknown";
  })();

  return {
    title,
    author,
    noteText,
    noteType,
    imageCandidates,
  };
}
"""
