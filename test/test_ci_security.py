from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_enforces_rust_python_and_secret_audits():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "cargo install cargo-audit --locked" in workflow
    assert "cargo audit" in workflow
    assert "pip-audit ." in workflow
    assert "gitleaks/gitleaks-action@v2" in workflow
    assert "GITLEAKS_CONFIG: .gitleaks.toml" in workflow
    assert 'cron: "17 9 * * 1"' in workflow


def test_release_bundle_declares_pooled_http_runtime():
    config = (ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    requirements = (ROOT / "proxy" / "requirements-runtime.txt").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "vendor-python-runtime.py" in config
    assert '"../../python-vendor": "python-vendor"' in config
    assert "httpx[http2]>=0.28,<1" in requirements
    assert '"httpx[http2]>=0.28,<1"' in project


def test_macos_package_triggers_for_biomedical_release_tags():
    workflow = (ROOT / ".github" / "workflows" / "macos-package.yml").read_text(
        encoding="utf-8"
    )
    push_trigger = workflow.split("  workflow_dispatch:", 1)[0]
    assert re.search(r'^ {6}- "bio-v\*"$', push_trigger, flags=re.MULTILINE)
    assert "startsWith(github.ref, 'refs/tags/bio-v')" in workflow


def test_linux_package_builds_deb_and_appimage_for_linux_tags():
    workflow = (ROOT / ".github" / "workflows" / "linux-package.yml").read_text(
        encoding="utf-8"
    )
    assert 'runs-on: ubuntu-22.04' in workflow
    assert 'libwebkit2gtk-4.1-dev' in workflow
    assert '"linux-v*"' in workflow
    assert 'bundle/deb/*.deb' in workflow
    assert 'bundle/appimage/*.AppImage' in workflow
    assert "gh release upload" in workflow
