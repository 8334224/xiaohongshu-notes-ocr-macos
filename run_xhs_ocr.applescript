-- 小红书笔记 OCR -> Obsidian
-- 从剪贴板读取小红书链接，通过本机已登录 Chrome (CDP 9222) 下载、OCR、写入 Obsidian

set clipText to (the clipboard as text)
set shellScript to "/Users/adi/Documents/小红书笔记OCR/run_xhs_local_chrome.sh"

try
	do shell script "export XHS_URL=" & quoted form of clipText & " && " & quoted form of shellScript
	display notification "已写入 Obsidian 笔记" with title "小红书 OCR" sound name "Glass"
on error errMsg
	display notification errMsg with title "小红书 OCR 失败" sound name "Basso"
end try
