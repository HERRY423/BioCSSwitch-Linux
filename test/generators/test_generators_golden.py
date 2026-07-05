#!/usr/bin/env python3
"""generator golden tests —— 默认离线（fixture replay），网络集成测试单独开。

离线（CI 默认）：
    python test/generators/test_generators_golden.py
    → 用 test/generators/fixtures/ 回放，跑 generator，与 golden/ 比对。

更新 golden（改了 generator 逻辑后）：
    python test/generators/test_generators_golden.py --update-golden

网络集成（手动，会打真实上游）：
    python test/generators/test_generators_golden.py --live
    → 不用 fixture，直接打网络，只检查结构不变式（不比对 golden，因为真实数据会变）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

# Windows 控制台默认 GBK，编不出 ✓/✗ 等符号；强制 UTF-8 输出（跨平台一致）。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "packs"))

from _lib import fixtures  # noqa: E402

_FIX_DIR = Path(__file__).parent / "fixtures"
_GOLDEN_DIR = Path(__file__).parent / "golden"


def _load_generator(rel: str):
    import importlib.util
    p = _ROOT / "packs" / "bio-workflows" / "generators" / rel
    spec = importlib.util.spec_from_file_location("gen_" + rel.replace(".py", ""), p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 每个 golden case：id, 跑一次 generator 得到可序列化 dict ────────────────

def _case_sr_pico() -> Dict[str, Any]:
    sr = _load_generator("sr_pico_builder.py")
    r = sr.build_pubmed_query(
        population="adults with type 2 diabetes",
        intervention="metformin monotherapy",
        comparator="placebo",
        outcome="cardiovascular events",
        study_type="RCT",
    )
    r["europepmc_query"] = sr.translate_to_europepmc(r["query"])
    r["cochrane_query"] = sr.translate_to_cochrane(r["query"])
    return r


def _case_td_egfr() -> Dict[str, Any]:
    td = _load_generator("td_druggability.py")
    return td.evaluate("EGFR")


def _case_td_brca1() -> Dict[str, Any]:
    td = _load_generator("td_druggability.py")
    return td.evaluate("BRCA1")


def _case_ct_landscape() -> Dict[str, Any]:
    ct = _load_generator("ct_landscape.py")
    studies = ct._fetch_all("non-small cell lung cancer", "pembrolizumab OR nivolumab", None, 1)
    return ct.build_landscape(studies)


_GOLDEN_CASES: List[Tuple[str, Callable[[], Dict[str, Any]]]] = [
    ("sr_pico", _case_sr_pico),
    ("td_egfr", _case_td_egfr),
    ("td_brca1", _case_td_brca1),
    ("ct_landscape", _case_ct_landscape),
]


# ── 结构不变式（--live 模式用；真实数据会变，只查形状）────────────────────

def _invariants(cid: str, out: Dict[str, Any]) -> List[str]:
    errs = []
    if cid == "sr_pico":
        if not out.get("query"):
            errs.append("sr_pico: query 为空")
        if "humans[MeSH]" not in out.get("query", ""):
            errs.append("sr_pico: 缺 humans filter")
        if "randomized controlled trial" not in out.get("query", "").lower():
            errs.append("sr_pico: 缺 RCT filter")
    elif cid.startswith("td_"):
        if not out.get("found"):
            errs.append(f"{cid}: found=False")
        elif out.get("verdict", {}).get("grade") not in {"A", "B", "C", "D"}:
            errs.append(f"{cid}: grade 非法")
    elif cid == "ct_landscape":
        if out.get("n_trials", 0) < 1:
            errs.append("ct_landscape: n_trials < 1")
        if not out.get("phase_status_matrix"):
            errs.append("ct_landscape: 缺 phase_status_matrix")
    return errs


def _normalize(obj: Any) -> Any:
    """把 dict 排序 key、把 Counter 里的 list-of-tuple 转成 list-of-list，便于稳定比对。"""
    return json.loads(json.dumps(obj, sort_keys=True, default=str))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update-golden", action="store_true")
    ap.add_argument("--live", action="store_true", help="打真实网络，只查结构不变式")
    args = ap.parse_args()

    if args.live:
        fixtures.deactivate()  # 确保不回放
        print("[golden] --live：打真实上游，只校验结构不变式")
    else:
        if not any(_FIX_DIR.glob("*.json")):
            print(f"[golden] 无 fixture（{_FIX_DIR}）。先跑 synth_fixtures.py 或 make_fixtures.py --live")
            return 2
        fixtures.activate(_FIX_DIR, mode="replay")

    _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    for cid, fn in _GOLDEN_CASES:
        try:
            out = fn()
        except fixtures.FixtureMiss as e:
            print(f"  ✗ {cid}: fixture 未命中 → {e}")
            failures += 1
            continue
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {cid}: 运行异常 → {e}")
            failures += 1
            continue

        if args.live:
            errs = _invariants(cid, out)
            if errs:
                for e in errs:
                    print(f"  ✗ {e}")
                failures += 1
            else:
                print(f"  ✓ {cid}（结构不变式通过）")
            continue

        golden_path = _GOLDEN_DIR / f"{cid}.json"
        norm = _normalize(out)
        if args.update_golden:
            golden_path.write_text(json.dumps(norm, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
            print(f"  ↻ {cid}: golden 已更新")
            continue
        if not golden_path.is_file():
            print(f"  ✗ {cid}: 无 golden 文件（先 --update-golden）")
            failures += 1
            continue
        expected = json.loads(golden_path.read_text("utf-8"))
        if _normalize(expected) == norm:
            print(f"  ✓ {cid}")
        else:
            print(f"  ✗ {cid}: 输出与 golden 不一致")
            # 打印首个差异字段
            _diff(expected, norm, cid)
            failures += 1

    if not args.live:
        st = fixtures.stats()
        print(f"[golden] fixture 命中 {st['hits']} / miss {st['misses']}")
        fixtures.deactivate()

    if args.update_golden:
        print("[golden] golden 已更新，未做比对")
        return 0
    if failures:
        print(f"[golden] {failures} 个 case 失败")
        return 1
    print("[golden] 全部通过 ✓")
    return 0


def _diff(a: Any, b: Any, path: str, depth: int = 0) -> None:
    if depth > 4:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                print(f"      + {path}.{k}（golden 缺）")
            elif k not in b:
                print(f"      - {path}.{k}（输出缺）")
            elif a[k] != b[k]:
                _diff(a[k], b[k], f"{path}.{k}", depth + 1)
    elif a != b:
        sa, sb = str(a)[:80], str(b)[:80]
        print(f"      ≠ {path}: golden={sa} | got={sb}")


if __name__ == "__main__":
    sys.exit(main())
