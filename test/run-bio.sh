#!/usr/bin/env bash
# BioCSSwitch offline biomedical regression layer.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
if ! command -v python3 >/dev/null 2>&1; then
  echo "S0_LAYER bio env-blocked (no python3)"; exit 0
fi
if python3 test/test_bio_offline.py; then
  echo "S0_LAYER bio pass"; exit 0
else
  echo "S0_LAYER bio fail"; exit 1
fi
