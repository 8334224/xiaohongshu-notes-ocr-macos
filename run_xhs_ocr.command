#!/bin/bash

cd /Users/adi/Documents/小红书笔记OCR || exit 1

if [ ! -d ".venv" ]; then
  echo "错误：未找到 .venv 虚拟环境"
  echo "请先在项目目录执行：python3 -m venv .venv"
  echo
  read -n 1 -s -r -p "按任意键退出..."
  exit 1
fi

source .venv/bin/activate

python3 main.py
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  open -a Notes
  exit 0
else
  echo
  read -n 1 -s -r -p "执行失败，按任意键关闭窗口..."
  exit $EXIT_CODE
fi