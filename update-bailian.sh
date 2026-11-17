#!/bin/bash
# 更新百炼个人 Token Plan 登录态，默认读取剪贴板中的 cURL (bash)。
# 用法：./update-bailian.sh
# 标准输入：pbpaste | ./update-bailian.sh --stdin

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    echo "Error: 未找到项目虚拟环境：$PYTHON" >&2
    echo "请先运行 python3 start.py 创建虚拟环境。" >&2
    exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/update_bailian_creds.py" "$@"
