#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "== python unittest =="
python3 -m unittest discover -s test -p 'test_*.py' -v
echo "== bio 离线测试（fixture 回放 / tool_executor / linter 隐私 / generator golden，零网络）=="
python3 test/test_bio_offline.py
echo "== node --test =="
node --test test/test_make_virtual_oauth.mjs
echo "== bash scripts =="
bash test/test_scripts.sh
echo "== bash ops scripts (doctor/verify-proxy/self-test) =="
bash test/test_ops_scripts.sh
echo "ALL GREEN"
