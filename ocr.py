"""Backward-compatible wrappers around the OCR engines."""

from __future__ import annotations

from pathlib import Path

from ocr_engine import ConcurrentOCREngine, VisionOCREngine


class VisionOCR(VisionOCREngine):
    """Compatibility wrapper for the existing single-image OCR interface."""

    def recognize_text(self, image_path: Path) -> str:
        """Recognize text from a local image path."""
        return self.ocr_image(str(image_path))


__all__ = ["ConcurrentOCREngine", "VisionOCR", "VisionOCREngine"]
