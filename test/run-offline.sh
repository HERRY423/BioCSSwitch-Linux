#!/usr/bin/env bash
# S0 offline unit layer: no loopback, no network, no upstream service.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
if ! command -v python3 >/dev/null 2>&1; then
  echo "S0_LAYER offline env-blocked (no python3)"; exit 0
fi
if python3 -m unittest discover -s test -p 'test_*.py' -v; then
  echo "S0_LAYER offline pass"; exit 0
else
  echo "S0_LAYER offline fail"; exit 1
fi
