"""macOS Vision OCR engines with optional concurrent batch processing."""

from __future__ import annotations

import argparse
import logging
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from collections import OrderedDict
from pathlib import Path
from typing import Any

from config import OCR_LANGUAGES
from text_cleaner import TextCleaner
from utils import AppError, clean_ocr_text

try:
    import Vision
    from Foundation import NSURL
except ImportError:  # pragma: no cover
    Vision = None
    NSURL = None

try:  # pragma: no cover - optional dependency
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = None

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
DEFAULT_OCR_TIMEOUT_SECONDS = 30
DEFAULT_MAX_WORKERS = 4
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_DELAY_SECONDS = 0.5
DEFAULT_BATCH_PAUSE_SECONDS = 0.1
MAX_SAFE_WORKERS = 4


class VisionOCREngine:
    """Perform OCR on a single image using macOS Vision."""

    def __init__(
        self,
        timeout_seconds: int = DEFAULT_OCR_TIMEOUT_SECONDS,
        text_cleaner: TextCleaner | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.logger = logger or LOGGER
        self.text_cleaner = text_cleaner or TextCleaner(logger=self.logger)

    def ocr_image(self, image_path: str) -> str:
        """Recognize text from a local image path."""
        path = Path(image_path).expanduser()
        if not path.exists():
            raise AppError(f"OCR 文件不存在：{path}")
        if not path.is_file():
            raise AppError(f"OCR 路径不是文件：{path}")

        self.logger.debug("ocr_image_start path=%s", path)
        raw_text = self._perform_vision_ocr(path)
        text = clean_ocr_text(raw_text)
        text = self.text_cleaner.clean_text(text)
        self.logger.debug("ocr_image_done path=%s chars=%d", path, len(text))
        return text

    def _perform_vision_ocr(self, image_path: Path) -> str:
        """Call macOS Vision OCR for a single image."""
        if Vision is None or NSURL is None:
            raise AppError(
                "缺少 Vision 依赖。请先执行 `pip install -r requirements.txt` 安装 PyObjC 相关依赖。"
            )

        file_url = NSURL.fileURLWithPath_(str(image_path))
        captured: dict[str, object] = {}

        def completion_handler(request, error):
            captured["error"] = error
            if error is not None:
                return

            strings: list[str] = []
            for observation in request.results() or []:
                candidates = observation.topCandidates_(1)
                if candidates:
                    strings.append(str(candidates[0].string()))
            captured["text"] = "\n".join(strings)

        request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(completion_handler)
        request.setRecognitionLanguages_(OCR_LANGUAGES)
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)

        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(file_url, None)
        success, error = handler.performRequests_error_([request], None)
        if not success:
            reason = str(error) if error is not None else "未知 Vision 错误"
            raise AppError(f"OCR 失败：{image_path.name}，{reason}")

        callback_error = captured.get("error")
        if callback_error is not None:
            raise AppError(f"OCR 失败：{image_path.name}，{callback_error}")

        return str(captured.get("text", ""))


class ConcurrentOCREngine(VisionOCREngine):
    """Batch OCR engine with bounded concurrency and retry-friendly failure tracking."""

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        batch_pause_seconds: float = DEFAULT_BATCH_PAUSE_SECONDS,
        timeout_seconds: int = DEFAULT_OCR_TIMEOUT_SECONDS,
        text_cleaner: TextCleaner | None = None,
        show_progress: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, text_cleaner=text_cleaner, logger=logger)
        self.max_workers = self._normalize_max_workers(max_workers)
        self.max_retries = max(0, int(max_retries))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self.batch_pause_seconds = max(0.0, float(batch_pause_seconds))
        self.show_progress = show_progress
        self.last_errors: dict[str, BaseException] = {}
        self.failed_images: list[str] = []

    def ocr_images(
        self,
        image_paths: list[str],
        max_workers: int | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    ) -> dict[str, str]:
        """OCR multiple images concurrently and return a path->text mapping."""
        if not image_paths:
            return {}

        worker_count = self._resolve_worker_count(image_paths, max_workers)
        retry_count = max(0, int(max_retries if max_retries is not None else self.max_retries))
        retry_delay_seconds = max(
            0.0,
            float(retry_delay_seconds if retry_delay_seconds is not None else self.retry_delay_seconds),
        )
        self.last_errors = {}
        self.failed_images = []
        self.logger.info(
            "ocr_batch_start count=%d max_workers=%d max_retries=%d retry_delay_seconds=%.2f",
            len(image_paths),
            worker_count,
            retry_count,
            retry_delay_seconds,
        )

        results: dict[str, str] = {}
        completed = 0
        progress = self._create_progress(total=len(image_paths))
        batches = [image_paths[index : index + worker_count] for index in range(0, len(image_paths), worker_count)]

        try:
            for batch_index, batch_paths in enumerate(batches, start=1):
                self.logger.info(
                    "ocr_batch_window_start batch=%d/%d batch_size=%d",
                    batch_index,
                    len(batches),
                    len(batch_paths),
                )
                with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="vision-ocr") as executor:
                    futures: dict[Future[str], str] = {}
                    start_times: dict[Future[str], float] = {}
                    for image_path in batch_paths:
                        future = executor.submit(
                            self._ocr_image_with_retry,
                            image_path,
                            retry_count,
                            retry_delay_seconds,
                        )
                        futures[future] = image_path
                        start_times[future] = time.monotonic()

                    pending = set(futures)
                    while pending:
                        for future in list(pending):
                            image_path = futures[future]
                            elapsed = time.monotonic() - start_times[future]
                            if future.done():
                                pending.remove(future)
                                completed += 1
                                try:
                                    results[image_path] = future.result()
                                    self.logger.info(
                                        "ocr_batch_item_done path=%s status=ok chars=%d",
                                        image_path,
                                        len(results[image_path]),
                                    )
                                except BaseException as exc:
                                    results[image_path] = ""
                                    self.last_errors[image_path] = exc
                                    self.failed_images.append(image_path)
                                    self.logger.warning(
                                        "ocr_batch_item_done path=%s status=error retries=%d error=%s",
                                        image_path,
                                        retry_count,
                                        exc,
                                    )
                                if progress is not None:
                                    progress.update(1)
                            elif elapsed > self.timeout_seconds:
                                pending.remove(future)
                                completed += 1
                                timeout_error = TimeoutError(f"OCR 超时：{Path(image_path).name}")
                                results[image_path] = ""
                                self.last_errors[image_path] = timeout_error
                                self.failed_images.append(image_path)
                                future.cancel()
                                self.logger.warning(
                                    "ocr_batch_item_done path=%s status=timeout seconds=%d",
                                    image_path,
                                    self.timeout_seconds,
                                )
                                if progress is not None:
                                    progress.update(1)
                        if pending:
                            time.sleep(0.05)
                self.logger.info(
                    "ocr_batch_window_done batch=%d/%d completed=%d",
                    batch_index,
                    len(batches),
                    completed,
                )
                if batch_index < len(batches) and self.batch_pause_seconds:
                    time.sleep(self.batch_pause_seconds)
        finally:
            if progress is not None:
                progress.close()

        self.logger.info(
            "ocr_batch_done count=%d failures=%d",
            completed,
            len(self.failed_images),
        )
        ordered_results: OrderedDict[str, str] = OrderedDict()
        for image_path in image_paths:
            ordered_results[image_path] = results.get(image_path, "")
        return ordered_results

    @staticmethod
    def _normalize_max_workers(max_workers: int) -> int:
        """Clamp OCR concurrency to a conservative safe range for macOS Vision."""
        return max(1, min(int(max_workers), MAX_SAFE_WORKERS))

    def _create_progress(self, total: int):
        """Create an optional tqdm progress bar."""
        if not self.show_progress or tqdm is None:
            return None
        return tqdm(total=total, desc="OCR", unit="img")

    def _resolve_worker_count(self, image_paths: list[str], max_workers: int | None) -> int:
        """Resolve a conservative worker count from config, CPU count, and image count."""
        requested = max_workers
        if requested is None:
            cpu_count = os.cpu_count() or 1
            requested = min(cpu_count, len(image_paths), self.max_workers)
        return self._normalize_max_workers(requested)

    def _ocr_image_with_retry(
        self,
        image_path: str,
        max_retries: int,
        retry_delay_seconds: float,
    ) -> str:
        """OCR one image with bounded retry attempts."""
        attempts = max_retries + 1
        last_error: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                self.logger.debug(
                    "ocr_retry_attempt path=%s attempt=%d/%d",
                    image_path,
                    attempt,
                    attempts,
                )
                return self.ocr_image(image_path)
            except BaseException as exc:
                last_error = exc
                should_retry = attempt < attempts
                self.logger.warning(
                    "ocr_retry_failed path=%s attempt=%d/%d will_retry=%s error=%s",
                    image_path,
                    attempt,
                    attempts,
                    str(should_retry).lower(),
                    exc,
                )
                if not should_retry:
                    break
                if retry_delay_seconds:
                    time.sleep(retry_delay_seconds)
        assert last_error is not None
        raise last_error


def _build_parser() -> argparse.ArgumentParser:
    """Build a tiny CLI for local OCR testing."""
    parser = argparse.ArgumentParser(description="Batch OCR local images with macOS Vision.")
    parser.add_argument("images", nargs="+", help="One or more local image paths")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS, help="Concurrent OCR workers")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES, help="Retry count per image")
    parser.add_argument("--retry-delay", type=float, default=DEFAULT_RETRY_DELAY_SECONDS, help="Retry delay in seconds")
    parser.add_argument("--timeout", type=int, default=DEFAULT_OCR_TIMEOUT_SECONDS, help="Per-image timeout in seconds")
    parser.add_argument("--debug", action="store_true", help="Enable verbose logs")
    parser.add_argument("--progress", action="store_true", help="Show tqdm progress bar when available")
    return parser


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    engine = ConcurrentOCREngine(
        max_workers=args.max_workers,
        max_retries=args.max_retries,
        retry_delay_seconds=args.retry_delay,
        timeout_seconds=args.timeout,
        show_progress=args.progress,
    )
    try:
        results = engine.ocr_images(args.images)
    except Exception as exc:  # pragma: no cover
        raise SystemExit(str(exc)) from exc

    for image_path in args.images:
        text = results.get(image_path, "")
        print(f"{image_path} -> {text[:50]}...")


if __name__ == "__main__":  # pragma: no cover
    main()
