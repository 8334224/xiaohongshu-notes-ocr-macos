from __future__ import annotations

import unittest
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import patch

from notes_writer import NotesWriter
from utils import AppError


class NotesWriterTests(unittest.TestCase):
    @patch("notes_writer.subprocess.run")
    def test_create_note_raises_permission_error_for_automation_denied(self, mock_run) -> None:
        mock_run.side_effect = CalledProcessError(
            returncode=1,
            cmd=["osascript"],
            stderr="Not authorized to send Apple events to Notes. (-1743)",
        )

        writer = NotesWriter("OCR")

        with self.assertRaisesRegex(AppError, "Notes 权限不足"):
            writer.create_note("标题", "正文")

    @patch("notes_writer.subprocess.run")
    def test_write_paragraphs_creates_one_note_per_non_empty_paragraph(self, mock_run) -> None:
        mock_run.return_value = CompletedProcess(args=["osascript"], returncode=0, stdout="", stderr="")
        writer = NotesWriter("OCR", delay_seconds=0)

        result = writer.write_paragraphs(["第一段", "", "  ", "第二段"], base_title="XHS Note")

        self.assertEqual(
            result,
            {
                "XHS Note 1": True,
                "XHS Note 2": True,
            },
        )
        self.assertEqual(writer.failed_notes, [])
        self.assertEqual(mock_run.call_count, 2)

    @patch("notes_writer.time.sleep")
    @patch("notes_writer.subprocess.run")
    def test_write_paragraphs_respects_delay_between_notes(self, mock_run, mock_sleep) -> None:
        mock_run.return_value = CompletedProcess(args=["osascript"], returncode=0, stdout="", stderr="")
        writer = NotesWriter("OCR", delay_seconds=0.3)

        writer.write_paragraphs(["第一段", "第二段", "第三段"], base_title="XHS Note")

        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_called_with(0.3)

    @patch("notes_writer.subprocess.run")
    def test_write_paragraphs_records_failures_and_keeps_successes(self, mock_run) -> None:
        mock_run.side_effect = [
            CompletedProcess(args=["osascript"], returncode=0, stdout="", stderr=""),
            CalledProcessError(returncode=1, cmd=["osascript"], stderr="generic failure"),
            CompletedProcess(args=["osascript"], returncode=0, stdout="", stderr=""),
        ]
        writer = NotesWriter("OCR", delay_seconds=0)

        result = writer.write_paragraphs(["第一段", "第二段", "第三段"], base_title="XHS Note")

        self.assertEqual(
            result,
            {
                "XHS Note 1": True,
                "XHS Note 2": False,
                "XHS Note 3": True,
            },
        )
        self.assertEqual(writer.failed_notes, ["XHS Note 2"])

    @patch("notes_writer.subprocess.run")
    def test_write_paragraphs_can_disable_index_suffix(self, mock_run) -> None:
        mock_run.return_value = CompletedProcess(args=["osascript"], returncode=0, stdout="", stderr="")
        writer = NotesWriter("OCR", append_index=False, delay_seconds=0)

        result = writer.write_paragraphs(["第一段"], base_title="XHS Note")

        self.assertEqual(result, {"XHS Note": True})


if __name__ == "__main__":
    unittest.main()
