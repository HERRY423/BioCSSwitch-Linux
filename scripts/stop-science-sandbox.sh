#!/usr/bin/env bash
# 停止隔离沙箱 Science（只停沙箱 data-dir 的守护进程，绝不影响真实实例 8765）。
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJ="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
SANDBOX_HOME="${SANDBOX_HOME:-$PROJ/.sandbox/home}"
DATA_DIR="$SANDBOX_HOME/.claude-science"
BIN="${SCIENCE_BIN:-}"
if [[ -z "$BIN" ]]; then
  if command -v claude-science >/dev/null 2>&1; then
    BIN="$(command -v claude-science)"
  else
    BIN="/Applications/Claude Science.app/Contents/Resources/bin/claude-science"
  fi
fi

if [[ ! -d "$DATA_DIR" ]]; then echo "沙箱不存在，无需停止。"; exit 0; fi

if HOME="$SANDBOX_HOME" "$BIN" stop --data-dir "$DATA_DIR" 2>&1 | tail -2; then
  echo "沙箱已停。真实实例 8765 未受影响。"
else
  rc=${PIPESTATUS[0]:-$?}
  echo "停止失败（退出码 $rc）。真实实例 8765 未受影响。" >&2
  exit "$rc"
fi
