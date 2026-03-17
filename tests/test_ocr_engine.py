from __future__ import annotations

import time
from pathlib import Path

import pytest

from ocr_engine import ConcurrentOCREngine, VisionOCREngine
from utils import AppError


class _FakeVisionEngine(VisionOCREngine):
    def __init__(self, outputs=None, errors=None, delay_seconds: float = 0.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.outputs = outputs or {}
        self.errors = errors or {}
        self.delay_seconds = delay_seconds

    def _perform_vision_ocr(self, image_path: Path) -> str:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if str(image_path) in self.errors:
            raise self.errors[str(image_path)]
        return self.outputs.get(str(image_path), "")


class _FakeConcurrentEngine(ConcurrentOCREngine):
    def __init__(self, outputs=None, errors=None, delay_seconds: float = 0.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.outputs = outputs or {}
        self.errors = errors or {}
        self.delay_seconds = delay_seconds
        self.call_counts: dict[str, int] = {}

    def _perform_vision_ocr(self, image_path: Path) -> str:
        image_key = str(image_path)
        self.call_counts[image_key] = self.call_counts.get(image_key, 0) + 1
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        error_value = self.errors.get(image_key)
        if isinstance(error_value, list):
            attempt_index = self.call_counts[image_key] - 1
            if attempt_index < len(error_value) and error_value[attempt_index] is not None:
                raise error_value[attempt_index]
        elif error_value is not None:
            raise error_value
        return self.outputs.get(image_key, "")


def test_single_image_success(tmp_path: Path) -> None:
    image_path = tmp_path / "sample1.png"
    image_path.write_bytes(b"x")
    engine = _FakeVisionEngine(outputs={str(image_path): " 第一行 😀\n第二行 😀"})

    text = engine.ocr_image(str(image_path))

    assert isinstance(text, str)
    assert text == "第一行\n第二行"


def test_single_image_missing_file() -> None:
    engine = _FakeVisionEngine()

    with pytest.raises(AppError, match="OCR 文件不存在"):
        engine.ocr_image("/tmp/does-not-exist.png")


def test_single_image_failure(tmp_path: Path) -> None:
    image_path = tmp_path / "sample1.png"
    image_path.write_bytes(b"x")
    engine = _FakeVisionEngine(errors={str(image_path): AppError("vision failed")})

    with pytest.raises(AppError, match="vision failed"):
        engine.ocr_image(str(image_path))


def test_batch_ocr(tmp_path: Path) -> None:
    image1 = tmp_path / "sample1.png"
    image2 = tmp_path / "sample2.png"
    image1.write_bytes(b"x")
    image2.write_bytes(b"y")
    engine = _FakeConcurrentEngine(
        max_workers=2,
        outputs={
            str(image1): "正文一",
            str(image2): "正文二",
        },
    )

    result = engine.ocr_images([str(image1), str(image2)])

    assert result[str(image1)] == "正文一"
    assert result[str(image2)] == "正文二"
    assert engine.failed_images == []
    assert list(result.keys()) == [str(image1), str(image2)]


def test_batch_ocr_records_failure_and_keeps_other_results(tmp_path: Path) -> None:
    image1 = tmp_path / "sample1.png"
    image2 = tmp_path / "sample2.png"
    image1.write_bytes(b"x")
    image2.write_bytes(b"y")
    engine = _FakeConcurrentEngine(
        max_workers=2,
        outputs={str(image1): "正文一"},
        errors={str(image2): AppError("vision failed")},
    )

    result = engine.ocr_images([str(image1), str(image2)])

    assert result[str(image1)] == "正文一"
    assert result[str(image2)] == ""
    assert engine.failed_images == [str(image2)]
    assert isinstance(engine.last_errors[str(image2)], AppError)
    assert list(result.keys()) == [str(image1), str(image2)]


def test_batch_ocr_timeout_marks_image_failed(tmp_path: Path) -> None:
    image1 = tmp_path / "sample1.png"
    image1.write_bytes(b"x")
    engine = _FakeConcurrentEngine(max_workers=1, timeout_seconds=1, delay_seconds=1.2)

    result = engine.ocr_images([str(image1)])

    assert result[str(image1)] == ""
    assert engine.failed_images == [str(image1)]
    assert isinstance(engine.last_errors[str(image1)], TimeoutError)


def test_batch_ocr_retries_and_eventually_succeeds(tmp_path: Path) -> None:
    image1 = tmp_path / "sample1.png"
    image1.write_bytes(b"x")
    engine = _FakeConcurrentEngine(
        max_workers=1,
        max_retries=2,
        retry_delay_seconds=0.0,
        outputs={str(image1): "最终成功"},
        errors={str(image1): [AppError("first fail"), None]},
    )

    result = engine.ocr_images([str(image1)], max_retries=2, retry_delay_seconds=0.0)

    assert result[str(image1)] == "最终成功"
    assert engine.failed_images == []
    assert str(image1) not in engine.last_errors
    assert engine.call_counts[str(image1)] == 2


def test_batch_ocr_retries_and_keeps_final_failure(tmp_path: Path) -> None:
    image1 = tmp_path / "sample1.png"
    image1.write_bytes(b"x")
    engine = _FakeConcurrentEngine(
        max_workers=1,
        max_retries=2,
        retry_delay_seconds=0.0,
        errors={str(image1): [AppError("fail-1"), AppError("fail-2"), AppError("fail-3")]},
    )

    result = engine.ocr_images([str(image1)], max_retries=2, retry_delay_seconds=0.0)

    assert result[str(image1)] == ""
    assert engine.failed_images == [str(image1)]
    assert isinstance(engine.last_errors[str(image1)], AppError)
    assert str(engine.last_errors[str(image1)]) == "fail-3"
    assert engine.call_counts[str(image1)] == 3


def test_batch_ocr_preserves_input_order_even_when_completion_order_differs(tmp_path: Path) -> None:
    image1 = tmp_path / "page1.png"
    image2 = tmp_path / "page2.png"
    image3 = tmp_path / "page3.png"
    image1.write_bytes(b"a")
    image2.write_bytes(b"b")
    image3.write_bytes(b"c")

    class _OutOfOrderEngine(_FakeConcurrentEngine):
        def _perform_vision_ocr(self, image_path: Path) -> str:
            if image_path.name == "page1.png":
                time.sleep(0.15)
            elif image_path.name == "page2.png":
                time.sleep(0.01)
            else:
                time.sleep(0.08)
            return super()._perform_vision_ocr(image_path)

    engine = _OutOfOrderEngine(
        max_workers=3,
        outputs={
            str(image1): "第一页",
            str(image2): "第二页",
            str(image3): "第三页",
        },
    )

    ordered_paths = [str(image1), str(image2), str(image3)]
    result = engine.ocr_images(ordered_paths)

    assert list(result.keys()) == ordered_paths
    assert list(result.values()) == ["第一页", "第二页", "第三页"]


def test_batch_ocr_uses_dynamic_worker_count_for_small_input(tmp_path: Path) -> None:
    image1 = tmp_path / "page1.png"
    image2 = tmp_path / "page2.png"
    image1.write_bytes(b"a")
    image2.write_bytes(b"b")
    engine = _FakeConcurrentEngine(max_workers=4)

    worker_count = engine._resolve_worker_count([str(image1), str(image2)], None)

    assert worker_count == 2


def test_batch_ocr_processes_large_input_in_windows_and_keeps_order(tmp_path: Path, caplog) -> None:
    images = []
    outputs = {}
    for index in range(5):
        image = tmp_path / f"page{index + 1}.png"
        image.write_bytes(b"x")
        images.append(str(image))
        outputs[str(image)] = f"第{index + 1}页"

    engine = _FakeConcurrentEngine(
        max_workers=2,
        batch_pause_seconds=0.0,
        outputs=outputs,
    )

    with caplog.at_level("INFO"):
        result = engine.ocr_images(images, max_workers=2)

    assert list(result.keys()) == images
    assert list(result.values()) == [f"第{index + 1}页" for index in range(5)]
    assert "ocr_batch_window_start batch=1/3 batch_size=2" in caplog.text
    assert "ocr_batch_window_start batch=2/3 batch_size=2" in caplog.text
    assert "ocr_batch_window_start batch=3/3 batch_size=1" in caplog.text


def test_batch_ocr_retry_logging_is_emitted(tmp_path: Path, caplog) -> None:
    image1 = tmp_path / "page1.png"
    image1.write_bytes(b"x")
    engine = _FakeConcurrentEngine(
        max_workers=1,
        batch_pause_seconds=0.0,
        outputs={str(image1): "恢复成功"},
        errors={str(image1): [AppError("fail-once"), None]},
    )

    with caplog.at_level("WARNING"):
        result = engine.ocr_images([str(image1)], max_retries=1, retry_delay_seconds=0.0)

    assert result[str(image1)] == "恢复成功"
    assert "ocr_retry_failed" in caplog.text
    assert "will_retry=true" in caplog.text
