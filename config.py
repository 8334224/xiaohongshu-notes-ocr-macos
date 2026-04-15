"""Application configuration."""

from pathlib import Path

OCR_FOLDER = Path.home() / "Desktop" / "OCR"
OCR_DEBUG_FOLDER = Path.home() / "Desktop" / "OCR_DEBUG"
DEFAULT_TXT_OUTPUT = OCR_FOLDER / "output.txt"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
MAX_IMAGES = 31
OBSIDIAN_VAULT_PATH = Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Obsidian"
DEFAULT_OBSIDIAN_FOLDER = "小红书"
DEFAULT_NOTES_FOLDER = OBSIDIAN_VAULT_PATH / DEFAULT_OBSIDIAN_FOLDER
OCR_LANGUAGES = ["zh-Hans", "zh-Hant", "en-US"]
XHS_DOWNLOAD_SUFFIX = "来自小红书自动下载"
PLAYWRIGHT_TIMEOUT_MS = 30000
PLAYWRIGHT_WAIT_AFTER_LOAD_MS = 2500
DEFAULT_CHROME_CDP_URL = "http://127.0.0.1:9222"
