from __future__ import annotations

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
