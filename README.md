# 小红书图片 OCR -> Obsidian

[![Release](https://img.shields.io/github/v/release/8334224/xiaohongshu-notes-ocr-macos)](https://github.com/8334224/xiaohongshu-notes-ocr-macos/releases/tag/v0.3.0)
![Python](https://img.shields.io/badge/python-3-blue)
![macOS](https://img.shields.io/badge/platform-macOS-black)
![Strategy](https://img.shields.io/badge/download-public__fetch_%E2%86%92_browser-green)
![Output](https://img.shields.io/badge/output-Obsidian_Markdown-purple)

一个面向 macOS 的本地 Python 工具：  
支持从小红书网页链接或本地图片提取正文；链接模式会先做 `note_type` 判定，视频笔记直接输出文字，图文笔记继续图片下载 + OCR，最终以 Markdown 文件写入 Obsidian vault 并导出纯文本。

## Overview

这个项目解决的是一个非常具体的 macOS 本地工作流：

1. 从小红书拿到一篇图文笔记链接，或手动准备一组图片
2. 先尝试免登录公开抓取正文文字与笔记元信息
3. 如果公开抓取失败或结果不足，自动回退到浏览器提取
4. 在链接模式最前面判定 `note_type`
5. 视频笔记直接输出标题 / 正文，不做图片下载和 OCR
6. 图文笔记继续下载图片并使用 macOS Vision OCR 识别图片文字
7. 对正文文字和 OCR 结果分别做轻量清洗
8. 按规则合并为一篇最终正文
9. 自动写入 Obsidian vault 的「小红书」文件夹，并导出纯文本

重点不是做通用爬虫，而是尽量稳定地跑通个人高频使用场景。  
当前实现里，`--use-local-chrome` 是更强的浏览器兜底，不是第一优先级。
配套的 `run_xhs_ocr.applescript` 可以从剪贴板一键静默执行整个流程，全程无终端窗口。

## Features

- 支持两种输入模式：
  - 本地图片目录模式
  - 剪贴板链接模式
- 支持多种小红书笔记 URL 形态与分享文案提取：
  - `/explore/<note_id>`
  - `/discovery/item/<note_id>`
  - `/discovery/note/<note_id>`
  - `/user/profile/<user_id>/<note_id>`
- 支持 `xhslink.com` 短链
- 支持从混合分享文案中自动提取链接
- URL 会先规范化，再进入统一下载流程
- 下载策略为“免登录公开抓取优先，浏览器兜底，随后按 `note_type` 分流”
- 公开抓取失败或结果不足时，自动回退到 Playwright 浏览器抓取
- 可选复用本机已登录 Chrome 会话（CDP），作为更强的浏览器兜底
- 链接模式下会尽量提取笔记正文文字 `note_text`
- 链接模式会优先判定笔记类型：
  - `video`：直接输出文字，跳过图片下载和 OCR
  - `image`：继续图片下载 + OCR
  - `unknown`：有图片组信号时按 `image`，否则按正文优先降级
- 正文文字会做小红书场景清洗：
  - 去标题重复前缀
  - 去尾部 hashtag 标签区
  - 去尾部编辑时间 / 日期 / 地点元信息
- 自动下载正文图片并按页码命名
- 使用 macOS Vision OCR 识别中英文混排文本
- 多图 OCR 使用并发批处理、自动重试、顺序保持与可选进度条
- OCR 文本会做后处理：
  - 去空行
  - 去重复行
  - 去 emoji
  - 保留段落结构
- 最终正文会按“正文文字在前，OCR 在后”的规则合并，并自动做轻量去重
- 自动写入 Obsidian vault 的「小红书」文件夹，格式为标准 Markdown (`.md`)
- 标题作为文件名，`/`、`:`、`*`、`?` 等非法字符会替换为 `-`
- 同名文件自动追加序号，避免覆盖
- 可选按段落生成独立 Obsidian 笔记：
  - 默认保持原来的单文件写入
  - 开启 `--notes-by-paragraphs` 后，会按段落逐条写入独立 `.md`
- 自动导出 `output.txt`
- 提供一键启动 `run_xhs_ocr.applescript`：
  - 从剪贴板直接读取链接并后台运行
  - 成功 / 失败通过通知中心提示，无终端窗口
  - 通过环境变量传递 URL，不依赖 `pbpaste` 权限
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

从系统剪贴板读取小红书笔记链接，先尝试免登录公开抓取，失败后自动回退到浏览器抓取，再按 `note_type` 进入“文字直出”或“图片 OCR”分支：

```bash
python3 main.py --from-clipboard
```

### 3. 剪贴板 + 本机已登录 Chrome

在“公开抓取优先”的基础上，进一步允许浏览器兜底阶段复用本机已登录的小红书会话。适合默认 `playwright` 打开后落到登录门槛页的情况：

```bash
python3 main.py --from-clipboard --use-local-chrome
```

自定义 CDP 地址：

```bash
python3 main.py --from-clipboard --use-local-chrome --chrome-cdp-url http://127.0.0.1:9223
```

## Workflow

```text
Clipboard URL / direct URL
        ↓
Resolve and normalize Xiaohongshu URL
        ↓
Try public HTTP fetch first
        ↓
If public fetch is incomplete or fails -> browser fallback
        ↓
If enabled, local Chrome can still be used as stronger fallback
        ↓
Extract title / author / note_text / note_type
        ↓
If note_type=video -> write text directly
        ↓
If note_type=image -> download images and run OCR
        ↓
Clean note_text and OCR text
        ↓
Merge note_text + OCR with light deduplication when OCR exists
        ↓
Write Markdown (.md) into Obsidian vault / 小红书 folder
        ↓
Export output.txt
```

## Download Strategy

当前链接下载模式的优先级是：

1. 先把剪贴板文本解析成结构化小红书 URL
2. 先尝试 `public_fetch` 免登录公开抓取 HTML
3. 在 `public_fetch` 阶段优先提取 `title / author / note_text / note_type`
4. 如果 `public_fetch` 已经明确判定为 `video`，且标题 / 正文信息可用，则直接按视频分支输出文字
5. 如果 `public_fetch` 失败，或结果质量不足，则回退到 `playwright`
6. 如果启用了 `--use-local-chrome`，浏览器兜底阶段会继续复用本机已登录 Chrome，也就是 `local_chrome`
7. 提取到 `title / author / note_text / note_type` 后，再决定走哪条链路：
   - `video`：直接输出文字
   - `image`：继续下载图片并 OCR
   - `unknown`：有图片组信号时按 `image`，否则按正文优先降级

补充说明：

- 链接模式下，程序会尽量同时提取 `note_text`
- `note_text` 提取失败不会阻断图片下载、OCR 或 Notes 主流程
- 明确的视频笔记会尽量在 `public_fetch` 阶段直接短路，避免回退到封面图下载或 OCR
- 视频笔记默认不会下载封面图，也不会做 OCR
- 本地图片模式不做正文文字抓取，只走 OCR

注意：

- 并不是所有小红书笔记都能通过免登录公开抓取拿到完整结果
- 遇到公开抓取失败、质量不足、登录门槛或风控页面时，程序会自动回退到浏览器方案
- `--use-local-chrome` 只影响浏览器兜底阶段，不会跳过公开抓取优先策略

这里的“公开抓取结果质量不足”目前至少包括：

- 缺少标题
- 缺少作者
- 没有抓到图片
- 标题仍是通用站点标题，例如 `小红书 - 你的生活兴趣社区`
- 作者字段明显是登录门槛文案

## Project Structure

```text
project/
  README.md
  requirements.txt
  main.py
  config.py
  parser.py
  ocr.py
  ocr_engine.py
  text_cleaner.py
  notes_writer.py
  formatter.py
  utils.py
  clipboard_reader.py
  xhs_url_validator.py
  xhs_public_fetcher.py
  downloader_utils.py
  xhs_downloader.py
  run_xhs_ocr.command
  run_xhs_ocr.applescript
  run_xhs_local_chrome.sh
  tests/
    test_formatter.py
    test_notes_writer.py
    test_ocr_engine.py
    test_parser.py
    test_public_fetcher.py
    test_text_cleaner.py
    test_v2_download.py
```

## Tech Stack

- Python 3
- Playwright
- macOS Vision OCR
- PyObjC
- AppleScript（静默启动器，不再依赖 osascript 写 Notes）
- Google Chrome CDP (optional)
- Obsidian（通过直接写 Markdown 文件到 vault 实现）

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

1. 在浏览器地址栏或分享文案中复制一条小红书图文笔记链接
2. 运行：

```bash
python3 main.py --from-clipboard
```

默认行为：

- 先做 URL 解析与规范化
- 先尝试 `public_fetch`
- 优先在 `public_fetch` 阶段判定 `note_type`
- `video`：直接输出标题 / 正文
- `image`：继续图片下载 + OCR
- `unknown`：有图片组信号时按 `image`，否则按正文优先
- 如 `public_fetch` 失败或结果不足，再自动回退到 `playwright`

### 一键静默启动（推荐）

项目提供了一个 `run_xhs_ocr.applescript`，可以从剪贴板直接读取链接、在后台运行整个流程、全程无终端窗口，成功或失败都通过 macOS 通知中心提示：

1. 在浏览器或小红书 App 中复制目标笔记链接
2. 运行 `run_xhs_ocr.applescript`（可以在 Script Editor 里运行、编译成 `.scpt`、或做成快捷指令 / 菜单栏按钮）

脚本做的事：

- 把系统剪贴板内容作为 `XHS_URL` 环境变量导出
- 以 `do shell script` 方式调用 `run_xhs_local_chrome.sh`
- 成功时显示通知 `已写入 Obsidian 笔记`
- 失败时显示通知并附带错误信息

这样就不需要打开 Terminal，也不会弹出任何窗口。

### 按段落生成独立 Notes

如果你希望把 OCR / 正文结果按段落拆成多个独立的 Obsidian `.md`，可以显式开启：

```bash
python3 main.py --notes-by-paragraphs
```

常用组合：

```bash
python3 main.py --notes-by-paragraphs --notes-delay-seconds 0.2 --notes-progress
```

可选参数：

- `--notes-by-paragraphs`
  - 开启后按段落生成独立 Notes
- `--notes-append-index` / `--no-notes-append-index`
  - 控制标题后是否追加序号
- `--notes-delay-seconds`
  - 控制每条 Note 的写入间隔
- `--notes-progress`
  - 显示 Notes 写入进度条（需要安装 `tqdm`）

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
- `public_fetch.html`
- `public_fetch_debug.txt`
- `public_fetch_debug.json`
- `debug_xhs_page.png`
- `debug_xhs_page.html`

行为规则：

- 成功：自动删除整个临时目录
- 失败：保留临时目录，并在终端打印路径

## Supported URL Shapes

当前支持：

- `https://www.xiaohongshu.com/explore/<note_id>?...`
- `https://www.xiaohongshu.com/discovery/item/<note_id>?...`
- `https://www.xiaohongshu.com/discovery/note/<note_id>?...`
- `https://www.xiaohongshu.com/user/profile/<user_id>/<note_id>?...`
- 小红书 App 分享文案中的 `http://xhslink.com/...`
- 混合分享文案中自动提取出的 URL

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

## Obsidian Output

默认写入路径：

```text
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian/小红书/
```

这是 iCloud 同步的 Obsidian vault 默认位置。如需改到本地 vault，修改 `config.py` 中的 `OBSIDIAN_VAULT_PATH` 和 `DEFAULT_OBSIDIAN_FOLDER`，或启动时通过 `--notes-folder` 覆盖。

写入规则：

- 每条笔记一个 `.md` 文件，标题作为文件名
- 文件名非法字符（`/`、`:`、`*`、`?`、`"`、`<`、`>`、`|`、`\`）统一替换为 `-`
- 文件名重复时自动追加序号（`标题 2.md`、`标题 3.md` …）
- 文件内容格式：
  ```markdown
  # {title}

  {body}
  ```

内容规则：

- 标题格式：`作者：文章标题`
- 本地图片模式：
  - 只输出 OCR 正文
- 链接模式：
  - `video`：标题和正文直接输出，不做 OCR
  - 无标题但有作者时，会在正文前输出一行 `作者：<name>`
  - 如果只有 `note_text`，只输出 `note_text`
  - 如果只有 OCR，只输出 OCR
  - 如果 `note_text` 和 OCR 都有，先输出 `note_text`，空两行，再接 OCR
- `note_text` 和 OCR 明显重复时，会优先保留 `note_text`，避免重复输出
- 开启 `--notes-by-paragraphs` 时：
  - 会先生成完整正文
  - 再按段落拆分
  - 每段生成独立 `.md` 文件
  - `output.txt` 仍然导出完整正文，不会拆成多个 txt
- 不保留文件名
- 不保留页码标记
- 多页 OCR 正文会按顺序连续拼接

## Note Text Cleanup

链接模式下提取到的 `note_text` 会做小红书场景清洗：

- 去掉标题完整重复或核心短句重复前缀
- 去掉尾部连续 hashtag 标签区
- 去掉尾部时间 / 日期 / 地点元信息
- 保留正文主体，不做总结和改写

例如：

- 标题：`一念空山-回响：孩子有自己的人生`
- 原始 `note_text`：`孩子有自己的人生对孩子的过度... #亲子关系 #家庭教育 编辑于 18 小时前 浙江`
- 清洗后：`对孩子的过度...`

## Debug & Troubleshooting

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
- `抓取策略：public_fetch 未成功：...`
  - 这是 `public_fetch` 阶段失败，程序会自动回退到 `playwright` 或 `local_chrome`
- `public_fetch 结果：... note_type=video ...`
  - 说明公开抓取阶段已经识别为视频；如果标题 / 作者 / 正文满足最低条件，会直接走视频分支，不再进入图片下载和 OCR
- `提取结果：note_type=..., title=..., author=..., image_url_count=..., has_note_text=...`
  - 这是浏览器或公开抓取阶段的摘要，能直接看到当前笔记被判成了 `video / image / unknown`
- `命中 video 分支，跳过图片下载和 OCR`
  - 当前笔记被当作视频或正文优先处理，不会进入 OCR
- `命中 image/OCR 分支，开始下载图片。note_type=...`
  - 当前笔记会继续进入图片下载 + OCR
- `公开抓取结果未通过质量判定：...`
  - 说明拿到了 HTML，但标题 / 作者 / 图片不完整，或只抓到 `meta` 封面图等低质量结果
- `note_text` 为空
  - 不会中断流程；链接模式下会退化成只输出 OCR
- `未提取到正文和 OCR 内容，跳过写入。`
  - 说明 `note_text` 和 OCR 最终都为空，本次不会创建空白 Notes，也不会写空白 `output.txt`
- `公开抓取调试摘要：.../public_fetch_debug.txt`
  - 打开该文件可查看最终 URL、提取方法、图片数量、质量判定原因和最终下载策略
- `.../public_fetch_debug.json`
  - 这是 `public_fetch` 阶段的结构化调试摘要，适合程序化排查
- `公开抓取 HTML 已保存：.../public_fetch.html`
  - 这是免登录公开抓取阶段拿到的原始 HTML，适合排查为什么质量判定未通过
- `本机 Chrome 未启动远程调试端口`
  - 先按 README 中命令启动带 `--remote-debugging-port` 的 Chrome
- `无法连接本机 Chrome 远程调试端口`
  - 检查端口、Chrome 进程和 `--chrome-cdp-url`
- `已连接本机 Chrome，但页面仍然要求登录或未进入正文页`
  - 确认远程调试 Chrome 中的小红书已登录，且可手动打开目标笔记
- `页面提取标题失败 / 页面提取作者失败 / 页面没有图片`
  - 页面结构变化，需要调整提取逻辑
- `本次运行失败，调试文件保留在：...`
  - 进入该临时目录，查看下载图片、`output.txt`、`public_fetch` HTML / TXT / JSON 摘要，以及浏览器截图和 HTML

## Testing

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

当前测试覆盖包括：

- URL 校验与规范化
- 结构化 URL 解析
- 免登录公开抓取
- `note_text` 提取与小红书正文清洗
- `note_text + OCR` 合并与轻量去重
- 并发 OCR、自动重试、批次处理与结果顺序保持
- OCR 文本清洗与段落拆分
- 按段落生成独立 Obsidian Markdown 笔记
- 公开抓取结果质量判定
- 下载文件名兼容现有 parser
- 手动模式与剪贴板模式目录策略
- 临时目录成功清理 / 失败保留
- 图片候选来源优先级
- clone-only 缺失图补回
- OCR 输入扫描忽略 debug 文件

## Limitations

- 当前支持图文笔记和视频笔记，但视频笔记默认只提取文字内容，不做封面图 OCR
- 不处理评论、相关推荐、用户主页
- 不支持多链接批量处理
- 不做复杂反爬绕过
- 作者提取在某些页面上仍可能抓到当前登录用户名，这一块后续可单独优化

## Roadmap

- 继续收敛小红书页面结构提取逻辑
- 进一步提升作者提取准确率
- 为下载器补更多真实页面场景测试
- 视需要增加 Swift 版本迁移路径
