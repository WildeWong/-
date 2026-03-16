#!/bin/bash
# 剧本拆解 - Script Breakdown
# 双击此文件启动 Web 应用

cd "$(dirname "$0")"

# ── Check Python ──────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "错误: 未找到 Python。请先安装 Python 3.9+。"
    echo "下载地址: https://www.python.org/downloads/"
    read -p "按回车键退出..."
    exit 1
fi

echo "使用 Python: $($PYTHON --version)"

# ── Install dependencies if needed ────────────────────────────
if ! $PYTHON -c "import flask" 2>/dev/null; then
    echo "正在安装依赖..."
    $PYTHON -m pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "错误: 依赖安装失败。"
        read -p "按回车键退出..."
        exit 1
    fi
fi

# ── Start Flask server ────────────────────────────────────────
PORT=5001
echo ""
echo "========================================"
echo "  剧本拆解 - Script Breakdown"
echo "  http://127.0.0.1:$PORT"
echo "========================================"
echo ""
echo "服务已启动，浏览器将自动打开。"
echo "按 Ctrl+C 停止服务。"
echo ""

# Open browser after a short delay
(sleep 1.5 && open "http://127.0.0.1:$PORT") &

$PYTHON app.py
