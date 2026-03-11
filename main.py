"""CLI entry point for Xiaohongshu image OCR to Apple Notes."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from clipboard_reader import read_clipboard_text
from config import DEFAULT_CHROME_CDP_URL, DEFAULT_NOTES_FOLDER, DEFAULT_TXT_OUTPUT, OCR_FOLDER
from downloader_utils import ensure_ocr_folder
from formatter import build_note_body, build_note_title
from notes_writer import NotesWriter
from ocr import VisionOCR
from parser import scan_and_validate_images_with_report
from utils import AppError, export_text_file, now
from xhs_downloader import XiaohongshuDownloader
from xhs_url_validator import validate_xhs_note_url


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="按文件名顺序 OCR ~/Desktop/OCR 下的小红书图片并写入苹果备忘录。"
    )
    parser.add_argument(
        "--notes-folder",
        default=DEFAULT_NOTES_FOLDER,
        help=f"苹果备忘录目标文件夹，默认：{DEFAULT_NOTES_FOLDER}",
    )
    parser.add_argument(
        "--txt-output",
        default=str(DEFAULT_TXT_OUTPUT),
        help=f"本地 txt 导出路径，默认：{DEFAULT_TXT_OUTPUT}",
    )
    parser.add_argument(
        "--from-clipboard",
        action="store_true",
        help="从系统剪贴板读取小红书笔记链接，自动下载图片后再进入 OCR 流程。",
    )
    parser.add_argument(
        "--use-local-chrome",
        action="store_true",
        help="通过 CDP 连接本机已登录的 Chrome，而不是启动新的 Playwright Chromium。",
    )
    parser.add_argument(
        "--chrome-cdp-url",
        default=DEFAULT_CHROME_CDP_URL,
        help=f"本机 Chrome 的 CDP 地址，默认：{DEFAULT_CHROME_CDP_URL}",
    )
    return parser.parse_args()


def run_existing_images_flow(input_folder: Path, notes_folder: str, txt_output: str) -> bool:
    """Run the existing OCR-to-Notes workflow on files already in OCR folder."""
    print(f"扫描 OCR 文件夹：{input_folder}")
    scan_result = scan_and_validate_images_with_report(input_folder)
    images = scan_result.images
    print(f"检测到 {len(images)} 张图片，标题：{images[0].title}")
    if scan_result.ignored_files:
        print(
            "已忽略非图片文件："
            f"{len(scan_result.ignored_files)} 个（{', '.join(scan_result.ignored_files)}）"
        )

    ocr_engine = VisionOCR()
    results: list[str] = []
    for image in images:
        print(f"OCR 处理中：第 {image.page} 页 - {image.path.name}")
        results.append(ocr_engine.recognize_text(image.path))

    generated_at = now()
    note_title = build_note_title(images[0].title, images[0].author, generated_at)
    note_body = build_note_body(str(input_folder), generated_at, images, results)

    print(f"写入苹果备忘录文件夹：{notes_folder}")
    NotesWriter(notes_folder).create_note(note_title, note_body)
    txt_output_path = Path(txt_output).expanduser()
    txt_export_error = None
    try:
        export_text_file(txt_output_path, note_body)
    except OSError as exc:
        txt_export_error = exc

    print("完成：已创建新的 Notes 备忘录。")
    print(f"识别图片数量：{len(images)}")
    print(f"笔记标题：{images[0].title}")
    print(f"备忘录标题：{note_title}")
    if txt_export_error is None:
        print(f"TXT 导出路径：{txt_output_path}")
    else:
        print(f"TXT 导出失败：{txt_export_error}")
    return txt_export_error is None


def create_clipboard_workdir() -> Path:
    """Create a per-run temporary workspace for clipboard mode."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(tempfile.mkdtemp(prefix=f"xhs_ocr_run_{timestamp}_"))
    print(f"本次临时工作目录：{path}")
    return path


def run_from_clipboard_flow(
    notes_folder: str,
    use_local_chrome: bool = False,
    chrome_cdp_url: str = DEFAULT_CHROME_CDP_URL,
) -> None:
    """Read a Xiaohongshu URL from clipboard, download images, then run OCR."""
    workdir = create_clipboard_workdir()
    workdir.mkdir(parents=True, exist_ok=True)
    txt_output_path = workdir / "output.txt"
    try:
        print("正在读取剪贴板...")
        clipboard_text = read_clipboard_text()
        url = validate_xhs_note_url(clipboard_text)
        print(f"已识别 URL：{url}")
        print("正在提取图片...")
        downloaded_paths = XiaohongshuDownloader(
            output_folder=workdir,
            debug_folder=workdir,
            use_local_chrome=use_local_chrome,
            chrome_cdp_url=chrome_cdp_url,
        ).download_from_url(url)
        print(f"已下载 {len(downloaded_paths)} 张图片到：{workdir}")
        print("开始进入 OCR 流程...")
        txt_success = run_existing_images_flow(workdir, notes_folder, str(txt_output_path))
        if txt_success:
            shutil.rmtree(workdir)
            print("本次运行成功，临时工作目录已自动清理。")
        else:
            print(f"本次运行失败，调试文件保留在：{workdir}")
    except Exception:
        print(f"本次运行失败，调试文件保留在：{workdir}")
        raise


def main() -> int:
    """CLI main wrapper."""
    args = parse_args()
    try:
        if args.from_clipboard:
            run_from_clipboard_flow(
                args.notes_folder,
                use_local_chrome=args.use_local_chrome,
                chrome_cdp_url=args.chrome_cdp_url,
            )
        else:
            ensure_ocr_folder()
            run_existing_images_flow(OCR_FOLDER, args.notes_folder, args.txt_output)
        return 0
    except AppError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"未预期错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
