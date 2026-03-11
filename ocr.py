"""macOS Vision OCR wrapper."""

from __future__ import annotations

from pathlib import Path

from config import OCR_LANGUAGES
from utils import AppError, clean_ocr_text

try:
    import Vision
    from Foundation import NSURL
except ImportError:  # pragma: no cover
    Vision = None
    NSURL = None


class VisionOCR:
    """Perform OCR using macOS Vision."""

    def recognize_text(self, image_path: Path) -> str:
        """Recognize text from a local image file."""
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

        request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(
            completion_handler
        )
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

        text = clean_ocr_text(str(captured.get("text", "")))
        if not text:
            raise AppError(f"OCR 失败：{image_path.name}，未识别到任何文本")

        return text
