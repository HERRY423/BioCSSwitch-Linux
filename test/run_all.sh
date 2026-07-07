#!/usr/bin/env bash
# S0 layered acceptance aggregator.
# Usage: run_all.sh [--require-release-ready]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
REQUIRE_RELEASE=0; [ "${1:-}" = "--require-release-ready" ] && REQUIRE_RELEASE=1
LAYERS="offline bio loopback scripts rust frontend"
any_fail=0; not_release=0
echo "== S0 layered acceptance gate =="
for L in $LAYERS; do
  line="$(bash "test/run-$L.sh" 2>&1 | tee /dev/stderr | grep -E '^S0_LAYER ' | tail -1)"
  st="$(echo "$line" | awk '{print $3}')"; [ -z "$st" ] && st="fail"
  eval "STATUS_$L=\"\$st\""
  case "$st" in
    fail) any_fail=1; not_release=1 ;;
    pass) : ;;
    *) not_release=1 ;;
  esac
done
echo "---- summary ----"
for L in $LAYERS; do
  eval "st=\"\$STATUS_$L\""
  printf '  %-9s %s\n' "$L" "$st"
done
echo "----"
if [ "$any_fail" -eq 0 ]; then echo "current-env clean: YES"; else echo "current-env clean: NO"; fi
if [ "$not_release" -eq 0 ]; then echo "release-ready green: YES"; else echo "release-ready green: NO"; fi
if [ "$any_fail" -ne 0 ]; then exit 1; fi
if [ "$REQUIRE_RELEASE" -eq 1 ] && [ "$not_release" -ne 0 ]; then exit 2; fi
exit 0
