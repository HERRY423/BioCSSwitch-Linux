#!/usr/bin/env bash
# S0 scripts 层：bash 脚本测试 + node OAuth 对拍（无 node 则 env-blocked）+ 运维 test_ops。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
fail=0
echo "== bash scripts =="
bash test/test_scripts.sh || fail=1
echo "== node oauth 对拍 =="
if command -v node >/dev/null 2>&1; then
  node --test test/test_make_virtual_oauth.mjs || fail=1
else
  echo "skip - node 对拍 env-blocked (no node)"
fi
echo "== ops (doctor 契约 + verify-proxy 自门) =="
bash test/test_ops_scripts.sh || fail=1
if [ "$fail" -eq 0 ]; then echo "S0_LAYER scripts pass"; exit 0; else echo "S0_LAYER scripts fail"; exit 1; fi
