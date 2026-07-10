#!/usr/bin/env python3
"""Vendor proxy runtime dependencies into the Tauri resource directory."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "python-vendor"
REQUIREMENTS = ROOT / "proxy" / "requirements-runtime.txt"
STAMP = DESTINATION / ".requirements.sha256"


def _complete() -> bool:
    required = ("httpx", "httpcore", "h2")
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    return (
        all((DESTINATION / name).is_dir() for name in required)
        and STAMP.is_file()
        and STAMP.read_text(encoding="utf-8").strip() == digest
    )


def main() -> int:
    if _complete():
        print(f"Python runtime vendor already complete: {DESTINATION}")
        return 0
    if importlib.util.find_spec("pip") is None:
        raise SystemExit("pip is required to vendor the packaged Python runtime")
    staging = DESTINATION.with_name("python-vendor.tmp")
    root = ROOT.resolve()
    if DESTINATION.resolve().parent != root or staging.resolve().parent != root:
        raise SystemExit("refusing to modify a Python vendor path outside the repository root")
    readme_path = DESTINATION / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--target",
            str(staging),
            "--requirement",
            str(REQUIREMENTS),
        ],
        check=True,
    )
    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)
    staging.replace(DESTINATION)
    if readme:
        (DESTINATION / "README.md").write_text(readme, encoding="utf-8")
    STAMP.write_text(
        hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest() + "\n",
        encoding="utf-8",
    )
    print(f"Vendored proxy runtime: {DESTINATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
