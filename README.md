# 小红书图片 OCR -> Apple Notes

一个面向 macOS 的本地 Python 工具：  
支持从小红书网页链接自动下载图文笔记图片，或直接处理本地图片，完成 OCR 后自动写入 Apple Notes，并导出纯文本。

## Overview

这个项目解决的是一个非常具体的个人工作流：

1. 从小红书拿到一篇图文笔记
2. 提取正文图片
3. 使用 macOS Vision OCR 识别文字
4. 做轻量文本清洗
5. 自动归档到 Apple Notes
6. 同步导出纯文本，方便检索、朗读和后续整理

重点不是做通用爬虫，而是尽量稳定地跑通个人高频使用场景。

## Features

- 支持两种输入模式：
  - 本地图片目录模式
  - 剪贴板链接模式
- 支持两种小红书笔记 URL 形态：
  - `/explore/<note_id>`
  - `/user/profile/<user_id>/<note_id>`
- URL 会先规范化，再进入统一下载流程
- 支持 Playwright 默认 Chromium 抓取
- 支持复用本机已登录 Chrome 会话（CDP）
- 自动下载正文图片并按页码命名
- 使用 macOS Vision OCR 识别中英文混排文本
- 自动写入 Apple Notes
- 自动导出 `output.txt`
- 剪贴板模式使用临时工作目录：
  - 成功后自动清理
  - 失败时保留下载图片、调试截图、HTML 和文本输出

## Modes

### 1. 本地图片模式

直接处理固定目录中的图片：

```bash
python3 main.py
```

输入目录：

```text
~/Desktop/OCR/
```

### 2. 剪贴板链接模式

从系统剪贴板读取小红书图文笔记链接，自动下载正文图片并进入 OCR：

```bash
python3 main.py --from-clipboard
```

### 3. 剪贴板 + 本机已登录 Chrome

复用本机已登录的小红书会话，适合默认 Playwright Chromium 打开后落到登录门槛页的情况：

```bash
python3 main.py --from-clipboard --use-local-chrome
```

自定义 CDP 地址：

```bash
python3 main.py --from-clipboard --use-local-chrome --chrome-cdp-url http://127.0.0.1:9223
```

## Workflow

```text
Clipboard URL / Local Images
        ↓
Download note images (optional)
        ↓
Filename parsing and ordering
        ↓
macOS Vision OCR
        ↓
Light text cleanup
        ↓
Write to Apple Notes
        ↓
Export output.txt
```

## Project Structure

```text
project/
  README.md
  requirements.txt
  main.py
  config.py
  parser.py
  ocr.py
  notes_writer.py
  formatter.py
  utils.py
  clipboard_reader.py
  xhs_url_validator.py
  downloader_utils.py
  xhs_downloader.py
  tests/
    test_formatter.py
    test_parser.py
    test_v2_download.py
```

## Tech Stack

- Python 3
- Playwright
- macOS Vision OCR
- PyObjC
- AppleScript
- Google Chrome CDP (optional)

## Installation

进入项目目录：

```bash
cd /Users/adi/Documents/小红书笔记OCR
```

创建并激活虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

安装 Playwright 浏览器：

```bash
playwright install chromium
```

## Quick Start

### 手动图片模式

把命名正确的图片放入：

```text
~/Desktop/OCR/
```

运行：

```bash
python3 main.py
```

### 剪贴板链接模式

1. 在浏览器地址栏复制一条小红书图文笔记链接
2. 运行：

```bash
python3 main.py --from-clipboard
```

### 剪贴板 + 本机 Chrome 模式

先启动一个带远程调试端口的独立 Chrome：

```bash
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/Library/Application Support/Google/Chrome-XHS-Automation"
```

然后：

1. 在这个 Chrome 中登录小红书
2. 确认能手动打开目标笔记正文
3. 复制链接到系统剪贴板
4. 运行：

```bash
python3 main.py --from-clipboard --use-local-chrome
```

## Directories

### 手动模式

固定输入目录：

```text
~/Desktop/OCR/
```

### 剪贴板模式

每次运行使用一个独立临时目录，例如：

```text
/var/folders/.../xhs_ocr_run_<timestamp>_<random>/
```

临时目录中会包含：

- 下载图片
- `output.txt`
- `debug_xhs_page.png`
- `debug_xhs_page.html`

行为规则：

- 成功：自动删除整个临时目录
- 失败：保留临时目录，并在终端打印路径

## Supported URL Shapes

当前支持：

- `https://www.xiaohongshu.com/explore/<note_id>?...`
- `https://www.xiaohongshu.com/user/profile/<user_id>/<note_id>?...`

内部会统一规范化为标准 `explore/<note_id>` URL 后再进入下载流程。

## Filename Rules

手动模式要求图片文件名符合：

```text
标题_页码_作者_来自小红书网页版.jpg
```

自动下载模式会生成：

```text
标题_页码_作者_来自小红书自动下载.jpg
```

两种命名都兼容当前 parser。

## Notes Output

- 标题格式：`作者：文章标题`
- 正文格式：纯 OCR 正文
- 不保留文件名
- 不保留页码标记
- 多页正文会按正文顺序连续拼接

## Troubleshooting

- `剪贴板为空`
  - 先复制一条小红书笔记 URL
- `剪贴板内容不是合法 URL`
  - 复制的是普通文本，不是地址栏链接
- `不是支持的小红书笔记网页链接`
  - 域名不是 `xiaohongshu.com`
- `不是支持的小红书图文笔记链接`
  - 链接不是当前支持的笔记页路径
- `Playwright 未安装`
  - 执行 `pip install -r requirements.txt`
- `Playwright 浏览器未安装`
  - 执行 `playwright install chromium`
- `本机 Chrome 未启动远程调试端口`
  - 先按 README 中命令启动带 `--remote-debugging-port` 的 Chrome
- `无法连接本机 Chrome 远程调试端口`
  - 检查端口、Chrome 进程和 `--chrome-cdp-url`
- `已连接本机 Chrome，但页面仍然要求登录或未进入正文页`
  - 确认远程调试 Chrome 中的小红书已登录，且可手动打开目标笔记
- `页面提取标题失败 / 页面提取作者失败 / 页面没有图片`
  - 页面结构变化，需要调整提取逻辑
- `本次运行失败，调试文件保留在：...`
  - 进入该临时目录，查看下载图片、`output.txt`、截图和 HTML

## Testing

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

当前测试覆盖包括：

- URL 校验与规范化
- 下载文件名兼容现有 parser
- 手动模式与剪贴板模式目录策略
- 临时目录成功清理 / 失败保留
- 图片候选来源优先级
- clone-only 缺失图补回
- OCR 输入扫描忽略 debug 文件

## Limitations

- 当前只支持小红书图文笔记，不处理视频
- 不处理评论、相关推荐、用户主页
- 不支持多链接批量处理
- 不做复杂反爬绕过
- 作者提取在某些页面上仍可能抓到当前登录用户名，这一块后续可单独优化

## Roadmap

- 继续收敛小红书页面结构提取逻辑
- 进一步提升作者提取准确率
- 为下载器补更多真实页面场景测试
- 视需要增加 Swift 版本迁移路径
