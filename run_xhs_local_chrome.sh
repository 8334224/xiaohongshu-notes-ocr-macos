#!/bin/zsh

set -euo pipefail

PROJECT_DIR="/Users/adi/Documents/小红书笔记OCR"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
MAIN_PY="$PROJECT_DIR/main.py"
CHROME_CDP_URL="http://127.0.0.1:9222/json/version"
CHROME_CDP_CONNECT_URL="http://127.0.0.1:9222"
CHROME_USER_DATA_DIR="$HOME/Library/Application Support/Google/Chrome-XHS-Automation"
RUN_ARGS=(--from-clipboard --use-local-chrome)

check_cdp() {
  curl -sf "$CHROME_CDP_URL" >/dev/null
}

check_playwright_cdp() {
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    try:
        _ = browser.contexts
    finally:
        browser.close()
PY
}

wait_for_cdp_stable() {
  local consecutive_success=0
  for _ in {1..15}; do
    if check_cdp; then
      consecutive_success=$((consecutive_success + 1))
      if [[ $consecutive_success -ge 3 ]]; then
        return 0
      fi
    else
      consecutive_success=0
    fi
    sleep 1
  done
  return 1
}

wait_for_playwright_cdp_stable() {
  local consecutive_success=0
  for _ in {1..15}; do
    if check_cdp && check_playwright_cdp; then
      consecutive_success=$((consecutive_success + 1))
      if [[ $consecutive_success -ge 2 ]]; then
        return 0
      fi
    else
      consecutive_success=0
    fi
    sleep 1
  done
  return 1
}

start_chrome() {
  open -na "Google Chrome" --args \
    --remote-debugging-port=9222 \
    --user-data-dir="$CHROME_USER_DATA_DIR"
}

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "错误：未找到可执行的虚拟环境 Python：$PYTHON_BIN" >&2
  exit 1
fi

if [[ ! -f "$MAIN_PY" ]]; then
  echo "错误：未找到主程序文件：$MAIN_PY" >&2
  exit 1
fi

if ! check_cdp; then
  start_chrome
fi

if ! wait_for_cdp_stable; then
  echo "错误：本机 Chrome 远程调试端口 9222 未就绪。" >&2
  exit 1
fi

if ! wait_for_playwright_cdp_stable; then
  start_chrome
  if ! wait_for_playwright_cdp_stable; then
    echo "错误：本机 Chrome 远程调试端口 9222 可见，但 Playwright 无法稳定连接。" >&2
    exit 1
  fi
fi

cd "$PROJECT_DIR"

if "$PYTHON_BIN" "$MAIN_PY" "${RUN_ARGS[@]}"; then
  exit 0
fi

sleep 2
if ! wait_for_playwright_cdp_stable; then
  start_chrome
  if ! wait_for_playwright_cdp_stable; then
    echo "错误：本机 Chrome 远程调试端口 9222 可见，但 Playwright 无法稳定连接。" >&2
    exit 1
  fi
fi

exec "$PYTHON_BIN" "$MAIN_PY" "${RUN_ARGS[@]}"
