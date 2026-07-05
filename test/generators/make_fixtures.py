#!/usr/bin/env python3
"""从**真实网络**录制 generator fixture（fidelity 高，覆盖合成 fixture）。

    python test/generators/make_fixtures.py --live

跑一遍每个 generator 的核心请求路径，把真实上游响应脱敏后落 test/generators/fixtures/。
录完记得 `test_generators_golden.py --update-golden` 刷新 golden。

**只在有网络时手动跑**。CI 默认用 synth_fixtures.py 产出的离线 fixture。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "packs"))

from _lib import fixtures  # noqa: E402

_FIX_DIR = Path(__file__).parent / "fixtures"


def _load(rel: str):
    import importlib.util
    p = _ROOT / "packs" / "bio-workflows" / "generators" / rel
    spec = importlib.util.spec_from_file_location("gen_" + rel.replace(".py", ""), p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", required=True,
                    help="确认要打真实网络（防误触）")
    args = ap.parse_args()
    if not args.live:
        print("加 --live 确认打网络")
        return 2

    _FIX_DIR.mkdir(parents=True, exist_ok=True)
    fixtures.activate(_FIX_DIR, mode="record")
    try:
        sr = _load("sr_pico_builder.py")
        td = _load("td_druggability.py")
        ct = _load("ct_landscape.py")
        print("[make_fixtures] sr_pico_builder（真实 NCBI MeSH）…")
        sr.build_pubmed_query(population="adults with type 2 diabetes",
                              intervention="metformin monotherapy",
                              comparator="placebo", outcome="cardiovascular events",
                              study_type="RCT")
        print("[make_fixtures] td_druggability EGFR / BRCA1（HGNC+UniProt+ChEMBL+OT）…")
        td.evaluate("EGFR")
        td.evaluate("BRCA1")
        print("[make_fixtures] ct_landscape（真实 CT.gov v2）…")
        studies = ct._fetch_all("non-small cell lung cancer",
                                "pembrolizumab OR nivolumab", None, 1)
        ct.build_landscape(studies)
    finally:
        st = fixtures.stats()
        fixtures.deactivate()
    print(f"[make_fixtures] 录制 {st['recorded']} 条真实 fixture。")
    print("[make_fixtures] 下一步：python test/generators/test_generators_golden.py --update-golden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
