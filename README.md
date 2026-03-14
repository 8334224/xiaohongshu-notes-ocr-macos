# 小红书图片 OCR -> Apple Notes

一个面向 macOS 的本地 Python 工具：  
支持从小红书网页链接或本地图片提取正文，优先尝试免登录公开抓取，失败后自动回退到浏览器抓取，完成 OCR 后写入 Apple Notes 并导出纯文本。

## Overview

这个项目解决的是一个非常具体的 macOS 本地工作流：

1. 从小红书拿到一篇图文笔记链接，或手动准备一组图片
2. 先尝试免登录公开抓取正文图片
3. 如果公开抓取失败或结果不足，自动回退到浏览器提取
4. 使用 macOS Vision OCR 识别图片文字
5. 做轻量文本清洗
6. 自动归档到 Apple Notes，并导出纯文本

重点不是做通用爬虫，而是尽量稳定地跑通个人高频使用场景。  
当前实现里，`--use-local-chrome` 是更强的浏览器兜底，不是第一优先级。

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
- 下载策略为“免登录公开抓取优先，浏览器兜底”
- 公开抓取失败或结果不足时，自动回退到 Playwright 浏览器抓取
- 可选复用本机已登录 Chrome 会话（CDP），作为更强的浏览器兜底
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

从系统剪贴板读取小红书图文笔记链接，先尝试免登录公开抓取，失败后自动回退到浏览器抓取，再进入 OCR：

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
Download images
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

## Download Strategy

当前链接下载模式的优先级是：

1. 先把剪贴板文本解析成结构化小红书 URL
2. 先尝试 `public_fetch` 免登录公开抓取 HTML
3. 如果 `public_fetch` 拿到完整结果，则直接下载正文图片
4. 如果 `public_fetch` 失败，或结果质量不足，则回退到 `playwright`
5. 如果启用了 `--use-local-chrome`，浏览器兜底阶段会继续复用本机已登录 Chrome，也就是 `local_chrome`

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
  notes_writer.py
  formatter.py
  utils.py
  clipboard_reader.py
  xhs_url_validator.py
  xhs_public_fetcher.py
  downloader_utils.py
  xhs_downloader.py
  run_xhs_ocr.command
  tests/
    test_formatter.py
    test_parser.py
    test_public_fetcher.py
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

1. 在浏览器地址栏或分享文案中复制一条小红书图文笔记链接
2. 运行：

```bash
python3 main.py --from-clipboard
```

默认行为：

- 先做 URL 解析与规范化
- 先尝试 `public_fetch`
- 如失败或结果不足，再自动回退到 `playwright`

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

## Notes Output

- 标题格式：`作者：文章标题`
- 正文格式：纯 OCR 正文
- 不保留文件名
- 不保留页码标记
- 多页正文会按正文顺序连续拼接

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
- `公开抓取结果未通过质量判定：...`
  - 说明拿到了 HTML，但标题 / 作者 / 图片不完整，或只抓到 `meta` 封面图等低质量结果
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
- 公开抓取结果质量判定
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
