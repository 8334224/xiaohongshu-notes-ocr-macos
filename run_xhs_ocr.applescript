-- 小红书笔记 OCR -> Apple Notes
-- 从剪贴板读取小红书链接，通过本机已登录 Chrome (CDP 9222) 下载、OCR、写入备忘录

set shellScript to "/Users/adi/Documents/小红书笔记OCR/run_xhs_local_chrome.sh"

tell application "Terminal"
	activate
	set cmdText to quoted form of shellScript & "; if [ $? -eq 0 ]; then open -a Notes; sleep 1; exit; else echo; read -n 1 -s -r -p '执行失败，按任意键关闭窗口...'; fi"
	do script cmdText
end tell
