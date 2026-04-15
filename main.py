"""CLI entry point for Xiaohongshu image OCR to Obsidian notes."""

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
from ocr_engine import ConcurrentOCREngine
from parser import scan_and_validate_images_with_report
from text_cleaner import TextCleaner
from utils import AppError, export_text_file, now, strip_redundant_leading_title
from xhs_downloader import XiaohongshuDownloader
from xhs_url_validator import validate_xhs_note_url

USE_PARSED_NOTE_TITLE = object()


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="按文件名顺序 OCR ~/Desktop/OCR 下的小红书图片并写入 Obsidian 笔记。"
    )
    parser.add_argument(
        "--notes-folder",
        default=str(DEFAULT_NOTES_FOLDER),
        help=f"Obsidian 笔记输出目录，默认：{DEFAULT_NOTES_FOLDER}",
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
    parser.add_argument(
        "--notes-by-paragraphs",
        action="store_true",
        help="将 OCR / 正文内容按段落拆分后，逐段写入独立 Obsidian 笔记。",
    )
    parser.add_argument(
        "--notes-append-index",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="按段落写入 Notes 时，是否在标题后追加序号，默认开启。",
    )
    parser.add_argument(
        "--notes-delay-seconds",
        type=float,
        default=0.2,
        help="按段落写入 Notes 时，每条 Note 的写入间隔秒数，默认：0.2。",
    )
    parser.add_argument(
        "--notes-progress",
        action="store_true",
        help="按段落写入 Notes 时显示进度条（需要已安装 tqdm）。",
    )
    return parser.parse_args()


def run_existing_images_flow(
    input_folder: Path,
    notes_folder: str | Path,
    txt_output: str,
    note_text: str | None = None,
    note_title_override: object = USE_PARSED_NOTE_TITLE,
    notes_by_paragraphs: bool = False,
    notes_append_index: bool = True,
    notes_delay_seconds: float = 0.2,
    notes_show_progress: bool = False,
) -> bool:
    """Run the existing OCR-to-Notes workflow on files already in OCR folder."""
    print(f"扫描 OCR 文件夹：{input_folder}")
    scan_result = scan_and_validate_images_with_report(input_folder)
    images = scan_result.images
    effective_title = images[0].title if note_title_override is USE_PARSED_NOTE_TITLE else str(note_title_override or "").strip()
    prepared_note_text = strip_redundant_leading_title(note_text, effective_title)
    if effective_title:
        print(f"检测到 {len(images)} 张图片，标题：{effective_title}")
    else:
        print(f"检测到 {len(images)} 张图片。")
    if scan_result.ignored_files:
        print(
            "已忽略非图片文件："
            f"{len(scan_result.ignored_files)} 个（{', '.join(scan_result.ignored_files)}）"
        )

    results: list[str] = []
    has_note_text = bool(prepared_note_text.strip())
    ocr_engine = ConcurrentOCREngine()
    image_paths = [str(image.path) for image in images]
    if len(images) > 1:
        print(f"OCR 并发处理中：{len(images)} 张图片，max_workers={ocr_engine.max_workers}")
    else:
        print("OCR 处理中：1 张图片")
    batch_results = ocr_engine.ocr_images(image_paths)

    for image in images:
        print(f"OCR 结果整理：第 {image.page} 页 - {image.path.name}")
        image_key = str(image.path)
        recognized_text = batch_results.get(image_key, "")
        error = ocr_engine.last_errors.get(image_key)
        if error is not None:
            if has_note_text:
                print(
                    f"提示：图片 {image.path.name} OCR 处理异常：{error}。"
                    " 继续使用正文内容。"
                )
                results.append("")
                continue
            raise AppError(f"OCR 失败：{image.path.name}，{error}") from error

        if not recognized_text.strip():
            print(f"提示：图片 {image.path.name} OCR 未识别到文本，已跳过该图片 OCR 内容。")
            results.append("")
            continue
        results.append(recognized_text)

    generated_at = now()
    note_title = build_note_title(effective_title, images[0].author, generated_at) if effective_title else ""
    note_body = build_note_body(str(input_folder), generated_at, images, results, note_text=prepared_note_text)
    if not note_body.strip():
        if note_title_override is not USE_PARSED_NOTE_TITLE and effective_title:
            print("未提取到正文和 OCR 内容，已仅保留标题写入。")
            NotesWriter(notes_folder).create_note(note_title, "")
            txt_output_path = Path(txt_output).expanduser()
            txt_export_error = None
            try:
                export_text_file(txt_output_path, note_title or effective_title)
            except OSError as exc:
                txt_export_error = exc
            print("完成：已写入 Obsidian 笔记。")
            print(f"识别图片数量：{len(images)}")
            print(f"笔记标题：{effective_title}")
            print(f"备忘录标题：{note_title}")
            if txt_export_error is None:
                print(f"TXT 导出路径：{txt_output_path}")
            else:
                print(f"TXT 导出失败：{txt_export_error}")
            return txt_export_error is None
        print("未提取到正文和 OCR 内容，跳过写入。")
        return True

    txt_output_path = Path(txt_output).expanduser()
    txt_export_error = None
    try:
        export_text_file(txt_output_path, note_body)
    except OSError as exc:
        txt_export_error = exc

    print(f"写入 Obsidian 笔记目录：{notes_folder}")
    if notes_by_paragraphs:
        paragraph_status = _write_paragraph_notes(
            notes_folder,
            note_body,
            note_title or effective_title or "XHS Note",
            append_index=notes_append_index,
            delay_seconds=notes_delay_seconds,
            show_progress=notes_show_progress,
        )
        failed_count = sum(1 for success in paragraph_status.values() if not success)
        print(f"段落笔记写入完成：成功 {len(paragraph_status) - failed_count} 条，失败 {failed_count} 条。")
    else:
        NotesWriter(notes_folder).create_note(note_title, note_body)

    print("完成：已写入 Obsidian 笔记。")
    print(f"识别图片数量：{len(images)}")
    if effective_title:
        print(f"笔记标题：{effective_title}")
        print(f"备忘录标题：{note_title}")
    else:
        print("笔记标题：无")
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


def write_note_text_only_flow(
    notes_folder: str | Path,
    txt_output: str,
    note_text: str | None,
    note_title: str | None = None,
    note_author: str | None = None,
) -> bool:
    """Write a note directly from extracted note text without OCR images."""
    effective_title = (note_title or "").strip()
    effective_author = (note_author or "").strip()
    rendered_title = _render_link_note_title(note_title, note_author)
    cleaned_note_text = strip_redundant_leading_title(note_text, effective_title)
    author_leading_line = f"作者：{effective_author}" if not effective_title and effective_author else ""
    if author_leading_line and cleaned_note_text:
        note_body = f"{author_leading_line}\n\n{cleaned_note_text}"
    else:
        note_body = author_leading_line or cleaned_note_text
    export_content = note_body
    if not note_body.strip() and not rendered_title.strip():
        print("未提取到正文和 OCR 内容，跳过写入。")
        return True

    print(f"写入 Obsidian 笔记目录：{notes_folder}")
    NotesWriter(notes_folder).create_note(rendered_title, note_body)
    txt_output_path = Path(txt_output).expanduser()
    txt_export_error = None
    try:
        if rendered_title and note_body:
            export_content = f"{rendered_title}\n\n{note_body}"
        elif rendered_title and not note_body:
            export_content = rendered_title
        export_text_file(txt_output_path, export_content)
    except OSError as exc:
        txt_export_error = exc

    print("完成：已写入 Obsidian 笔记。")
    print("识别图片数量：0")
    if effective_title:
        print(f"笔记标题：{effective_title}")
        if rendered_title:
            print(f"备忘录标题：{rendered_title}")
    else:
        print("笔记标题：无")
        if effective_author:
            print(f"笔记作者：{effective_author}")
    if txt_export_error is None:
        print(f"TXT 导出路径：{txt_output_path}")
    else:
        print(f"TXT 导出失败：{txt_export_error}")
    return txt_export_error is None


def _render_link_note_title(note_title: str | None, note_author: str | None) -> str:
    """Render the final title line for a link note."""
    cleaned_title = (note_title or "").strip()
    cleaned_author = (note_author or "").strip()
    if cleaned_title and cleaned_author:
        return build_note_title(cleaned_title, cleaned_author, now())
    return cleaned_title


def _write_paragraph_notes(
    notes_folder: str | Path,
    note_body: str,
    base_title: str,
    append_index: bool,
    delay_seconds: float,
    show_progress: bool,
) -> dict[str, bool]:
    """Split note body into paragraphs and write one Obsidian note per paragraph."""
    cleaner = TextCleaner()
    paragraphs = cleaner.structure_text(note_body)
    writer = NotesWriter(
        notes_folder,
        append_index=append_index,
        delay_seconds=delay_seconds,
        show_progress=show_progress,
    )
    return writer.write_paragraphs(paragraphs, base_title=base_title or "XHS Note")


def run_from_clipboard_flow(
    notes_folder: str | Path,
    use_local_chrome: bool = False,
    chrome_cdp_url: str = DEFAULT_CHROME_CDP_URL,
    notes_by_paragraphs: bool = False,
    notes_append_index: bool = True,
    notes_delay_seconds: float = 0.2,
    notes_show_progress: bool = False,
) -> None:
    """Read a Xiaohongshu URL from clipboard, download images, then run OCR."""
    workdir = create_clipboard_workdir()
    workdir.mkdir(parents=True, exist_ok=True)
    txt_output_path = workdir / "output.txt"
    try:
        print(f"运行入口：{Path(__file__).resolve()} [video-routing-20260317]")
        print("正在读取剪贴板...")
        clipboard_text = read_clipboard_text()
        url = validate_xhs_note_url(clipboard_text)
        print(f"开始处理链接：{url}")
        print("正在提取图片...")
        download_result = XiaohongshuDownloader(
            output_folder=workdir,
            debug_folder=workdir,
            use_local_chrome=use_local_chrome,
            chrome_cdp_url=chrome_cdp_url,
        ).download_from_url_with_result(url)
        print(
            "主流程收到结果："
            f"note_type={download_result.note_type}, "
            f"title={download_result.note_title or ''}, "
            f"author={download_result.note_author or ''}, "
            f"image_path_count={len(download_result.paths)}, "
            f"has_note_text={bool((download_result.note_text or '').strip())}"
        )
        print(f"已下载 {len(download_result.paths)} 张图片到：{workdir}")
        if download_result.note_type == "video" or (
            download_result.note_type == "unknown" and not download_result.paths
        ):
            if download_result.note_type == "video":
                print("命中 video 分支，跳过图片下载和 OCR")
            else:
                print("命中正文优先分支，跳过图片下载和 OCR")
            txt_success = write_note_text_only_flow(
                notes_folder,
                str(txt_output_path),
                note_text=download_result.note_text,
                note_title=download_result.note_title,
                note_author=download_result.note_author,
            )
        else:
            if download_result.note_type == "video":
                raise AppError("逻辑错误：video 分支不应进入图片下载。")
            print(f"命中 image/OCR 分支，开始下载图片。note_type={download_result.note_type}")
            print("开始进入 OCR 流程...")
            txt_success = run_existing_images_flow(
                workdir,
                notes_folder,
                str(txt_output_path),
                note_text=download_result.note_text,
                note_title_override=download_result.note_title,
                notes_by_paragraphs=notes_by_paragraphs,
                notes_append_index=notes_append_index,
                notes_delay_seconds=notes_delay_seconds,
                notes_show_progress=notes_show_progress,
            )
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
                notes_by_paragraphs=args.notes_by_paragraphs,
                notes_append_index=args.notes_append_index,
                notes_delay_seconds=args.notes_delay_seconds,
                notes_show_progress=args.notes_progress,
            )
        else:
            ensure_ocr_folder()
            run_existing_images_flow(
                OCR_FOLDER,
                args.notes_folder,
                args.txt_output,
                notes_by_paragraphs=args.notes_by_paragraphs,
                notes_append_index=args.notes_append_index,
                notes_delay_seconds=args.notes_delay_seconds,
                notes_show_progress=args.notes_progress,
            )
        return 0
    except AppError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"未预期错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
