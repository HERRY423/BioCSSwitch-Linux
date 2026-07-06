#!/usr/bin/env bash
# S0 分层验收门汇总器（保留老入口名，只汇总不承载测试细节）。
# 用法：run_all.sh [--require-release-ready]
#   两种总判定：
#     current-env clean = 本环境无 fail（可有 env-blocked / needs-real-machine）
#     release-ready green = 5 层均 pass 且无 env-blocked
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
REQUIRE_RELEASE=0; [ "${1:-}" = "--require-release-ready" ] && REQUIRE_RELEASE=1
LAYERS="offline loopback scripts rust frontend"
# 注：本机 /bin/bash 是 3.2（macOS 系统自带，不支持 declare -A），
# 用「STATUS_<layer>」这组固定命名的普通变量代替关联数组，行为等价。
any_fail=0; not_release=0
echo "== S0 分层验收门 =="
for L in $LAYERS; do
  line="$(bash "test/run-$L.sh" 2>&1 | tee /dev/stderr | grep -E '^S0_LAYER ' | tail -1)"
  st="$(echo "$line" | awk '{print $3}')"; [ -z "$st" ] && st="fail"   # 无标记行 = 当 fail 处理（不静默）
  eval "STATUS_$L=\"\$st\""
  case "$st" in
    fail) any_fail=1; not_release=1 ;;
    pass) : ;;
    *) not_release=1 ;;   # env-blocked / skipped / needs-real-machine 都不满足 release-ready
  esac
done
echo "---- 汇总 ----"
for L in $LAYERS; do
  eval "st=\"\$STATUS_$L\""
  printf '  %-9s %s\n' "$L" "$st"
done
echo "----"
if [ "$any_fail" -eq 0 ]; then echo "current-env clean: YES（本环境无 fail）"; else echo "current-env clean: NO（有 fail）"; fi
if [ "$not_release" -eq 0 ]; then echo "release-ready green: YES（5 层均 pass、无 env-blocked）"; else echo "release-ready green: NO（有 env-blocked / fail，须在具备全部能力的机器复跑）"; fi
if [ "$any_fail" -ne 0 ]; then exit 1; fi
if [ "$REQUIRE_RELEASE" -eq 1 ] && [ "$not_release" -ne 0 ]; then exit 2; fi
exit 0
