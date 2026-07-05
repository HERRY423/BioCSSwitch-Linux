#!/usr/bin/env python3
"""bio_eval Lab —— 端到端评测编排器。

单次 `run.py` 打一发拿一份得分；`lab.py` 是**科研级**评测：
  - 多次重复（`--iterations N`）算 mean / stdev / var
  - profile 矩阵（`--matrix profile1:secret1,profile2:secret2`）
  - 生成 HTML 报告卡 + JUnit XML（供 CI）
  - 每个 case 保留原始 request/response 到 `results/artifacts/`（可选）

设计原则：
  - **诚实报告**：低样本 stdev 不可信，报告里显示 n 与置信提示
  - **可追溯**：所有指标都能反推到具体 case 的 raw artifact
  - **CI 友好**：--junit-xml + --fail-under 结合 GitHub Actions 用

用法：
    python test/bio_eval/lab.py --matrix deepseek:http://127.0.0.1:18991/abc \\
        --iterations 3 --html-report reports/eval.html \\
        --junit-xml reports/eval.junit.xml
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent))
from cases import cases_by_ids  # noqa: E402
from run import _mark, run_case, summarize, _RESULTS_DIR  # noqa: E402


_ARTIFACTS_DIR = _RESULTS_DIR / "artifacts"


def _parse_matrix(s: str) -> List[Tuple[str, str]]:
    """解析 `label:proxy_url,label:proxy_url` → [(label, proxy_url), ...]"""
    out = []
    for entry in s.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(f"矩阵项缺少 ':' → {entry}")
        # 从右往左切一次不够（url 里含 :）；找第一个 : 之前作 label
        i = entry.index(":")
        label = entry[:i].strip()
        proxy = entry[i + 1:].strip()
        if not label or not proxy:
            raise ValueError(f"矩阵项 label 或 proxy 空 → {entry}")
        out.append((label, proxy))
    return out


def _run_matrix(matrix: List[Tuple[str, str]], cases: List[Dict], iterations: int,
                model: str, save_artifacts: bool) -> Dict[str, Any]:
    """跑矩阵 × iterations，返回聚合结果。"""
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    all_runs: Dict[str, List[List[Dict]]] = {}  # label → [iter1_results, iter2_results, ...]
    for label, proxy in matrix:
        print(f"\n[lab] provider = {label} (proxy={proxy})")
        iter_results: List[List[Dict]] = []
        for it in range(iterations):
            print(f"  iteration {it + 1}/{iterations}")
            run_results: List[Dict] = []
            for c in cases:
                print(f"    ▶ {c['id']:20s}", end=" ", flush=True)
                r = run_case(proxy, c, model)
                run_results.append(r)
                if r.get("score") is None:
                    print(f"[{r['verdict']}] {(r.get('reason') or '')[:60]}")
                else:
                    print(f"[{r['verdict']}] score={r['score']:.2f}")
                if save_artifacts:
                    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
                    art = {
                        "label": label, "iter": it, "case_id": c["id"],
                        "prompt": c["prompt"], "tools": c.get("tools"),
                        "result": r,
                    }
                    ap = _ARTIFACTS_DIR / f"{ts}-{label}-{it}-{c['id']}.json"
                    ap.write_text(json.dumps(art, ensure_ascii=False, indent=2), "utf-8")
                    os.chmod(ap, 0o600)
            iter_results.append(run_results)
        all_runs[label] = iter_results
    return {"ts": ts, "matrix": all_runs}


def _aggregate(all_runs: Dict[str, List[List[Dict]]]) -> Dict[str, Any]:
    """按 (label, case_id) 聚合 mean / stdev；按 (label, category) 聚合分类分。"""
    per_case: Dict[str, Dict[str, Dict[str, Any]]] = {}
    per_category: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for label, iters in all_runs.items():
        per_case[label] = {}
        cat_scores: Dict[str, List[float]] = {}
        # 每个 case_id 在所有 iter 里的得分
        case_scores: Dict[str, List[float]] = {}
        case_verdicts: Dict[str, List[str]] = {}
        for it_results in iters:
            for r in it_results:
                cid = r["id"]
                if r.get("score") is not None:
                    case_scores.setdefault(cid, []).append(float(r["score"]))
                    cat_scores.setdefault(r["category"], []).append(float(r["score"]))
                case_verdicts.setdefault(cid, []).append(r["verdict"])
        for cid, scores in case_scores.items():
            per_case[label][cid] = {
                "n": len(scores),
                "mean": round(statistics.mean(scores), 3),
                "stdev": round(statistics.stdev(scores), 3) if len(scores) >= 2 else 0.0,
                "min": round(min(scores), 3),
                "max": round(max(scores), 3),
                "verdicts": case_verdicts[cid],
            }
        per_category[label] = {}
        for cat, scores in cat_scores.items():
            per_category[label][cat] = {
                "n": len(scores),
                "mean": round(statistics.mean(scores), 3),
                "stdev": round(statistics.stdev(scores), 3) if len(scores) >= 2 else 0.0,
                "mark": _mark(statistics.mean(scores)),
            }
    return {"per_case": per_case, "per_category": per_category}


def _write_html(agg: Dict[str, Any], matrix_labels: List[str], out: Path,
                title: str) -> None:
    per_cat = agg["per_category"]
    all_cats = sorted({c for lbl in matrix_labels for c in per_cat.get(lbl, {})})
    html_rows = []
    for cat in all_cats:
        row = [f"<td>{cat}</td>"]
        for lbl in matrix_labels:
            d = per_cat.get(lbl, {}).get(cat)
            if not d:
                row.append("<td>—</td>")
                continue
            confidence = "" if d["n"] >= 3 else f' <span class="lowconf">n={d["n"]}</span>'
            row.append(
                f'<td class="{_verdict_cls(d["mark"])}">{d["mark"]} '
                f'{d["mean"]:.2f}<br><small>±{d["stdev"]:.2f}{confidence}</small></td>'
            )
        html_rows.append("<tr>" + "".join(row) + "</tr>")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>{_esc(title)}</title>
<style>
  body{{font:14px -apple-system,BlinkMacSystemFont,sans-serif;max-width:1100px;margin:2em auto;padding:0 1em}}
  h1{{border-bottom:2px solid #333;padding-bottom:6px}}
  table{{border-collapse:collapse;width:100%;margin:1em 0}}
  th,td{{border:1px solid #ccc;padding:8px 10px;text-align:left;vertical-align:top}}
  th{{background:#f4f4f4;font-weight:600}}
  td.ok{{background:#e6ffed;color:#0a7f2e}}
  td.warn{{background:#fff4e5;color:#a25f00}}
  td.fail{{background:#ffe9ea;color:#b30015}}
  small{{color:#666}}
  .lowconf{{color:#a25f00;font-style:italic}}
  .note{{color:#666;font-size:12px;margin:0.5em 0}}
</style></head><body>
<h1>{_esc(title)}</h1>
<p class="note">生成时间 {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}。阈值：✓✓≥0.9 ✓≥0.7 ⚠≥0.4 ✗&lt;0.4；n&lt;3 时 stdev 不可信（标注 low confidence）。</p>

<h2>按类别汇总</h2>
<table>
  <thead><tr><th>类别</th>{"".join(f'<th>{_esc(l)}</th>' for l in matrix_labels)}</tr></thead>
  <tbody>{"".join(html_rows)}</tbody>
</table>

<h2>说明</h2>
<ul>
  <li>数值 = 该类别所有 case 得分均值；n 是有效样本数（跨 iteration + case）。</li>
  <li>类别里出现 profile_error（上游 401/500 等）不会计入均值，只在 case 级 raw artifact 里保留。</li>
  <li>要看每个 case 的具体行为，看 <code>results/artifacts/</code> 下的 JSON 原始记录。</li>
</ul>
</body></html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, "utf-8")


def _verdict_cls(mark: str) -> str:
    if mark == "✓✓" or mark == "✓":
        return "ok"
    if mark == "⚠":
        return "warn"
    return "fail"


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _write_junit(agg: Dict[str, Any], all_runs: Dict[str, List[List[Dict]]],
                 out: Path, fail_under: float) -> int:
    """写 JUnit XML；返回失败的 case 数（用于退出码）。
    每个 (label, case_id) 是一条 testcase；mean 低于 fail_under 视为 failure。"""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<testsuites>']
    total = 0
    fails = 0
    for label, per_case in agg["per_case"].items():
        cases_count = len(per_case)
        case_fails = sum(1 for d in per_case.values() if d["mean"] < fail_under)
        total += cases_count
        fails += case_fails
        lines.append(
            f'  <testsuite name="{_esc(label)}" tests="{cases_count}" failures="{case_fails}">'
        )
        for cid, d in per_case.items():
            lines.append(
                f'    <testcase classname="{_esc(label)}" name="{_esc(cid)}" time="0">'
            )
            if d["mean"] < fail_under:
                lines.append(
                    f'      <failure message="score {d["mean"]} &lt; {fail_under}">'
                    f'mean={d["mean"]} stdev={d["stdev"]} n={d["n"]} verdicts={_esc(",".join(d["verdicts"]))}'
                    f'</failure>'
                )
            lines.append('    </testcase>')
        lines.append('  </testsuite>')
    lines.append('</testsuites>')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), "utf-8")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", required=True,
                    help='格式：label:proxy_url,label:proxy_url')
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--cases", help="逗号分隔的 case id / category")
    ap.add_argument("--html-report", type=Path)
    ap.add_argument("--junit-xml", type=Path)
    ap.add_argument("--fail-under", type=float, default=0.5,
                    help="mean 低于此值算 failure（JUnit）")
    ap.add_argument("--save-artifacts", action="store_true",
                    help="保存每个 case 的 raw request/response 到 results/artifacts/")
    args = ap.parse_args()

    matrix = _parse_matrix(args.matrix)
    if not matrix:
        print("[lab] matrix 为空")
        return 2
    cases = cases_by_ids(args.cases.split(",") if args.cases else None)
    if not cases:
        print("[lab] cases 匹配到 0 个")
        return 2

    result = _run_matrix(matrix, cases, args.iterations, args.model, args.save_artifacts)
    agg = _aggregate(result["matrix"])

    # 落一份 JSON 结果
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    labels = [lbl for lbl, _ in matrix]
    out_json = _RESULTS_DIR / f"lab-{result['ts']}.json"
    out_json.write_text(json.dumps({
        "ts": result["ts"], "iterations": args.iterations, "matrix_labels": labels,
        "aggregate": agg, "raw": result["matrix"],
    }, ensure_ascii=False, indent=2), "utf-8")
    os.chmod(out_json, 0o600)
    print(f"\n[lab] JSON → {out_json}")

    if args.html_report:
        _write_html(agg, labels, args.html_report,
                    f"bio_eval Lab 报告 · {result['ts']}")
        print(f"[lab] HTML → {args.html_report}")

    fails = 0
    if args.junit_xml:
        fails = _write_junit(agg, result["matrix"], args.junit_xml, args.fail_under)
        print(f"[lab] JUnit XML → {args.junit_xml} ({fails} failures)")

    print("\n[lab] 每 provider 每类别（mark  mean±stdev, n）:")
    for lbl in labels:
        print(f"  {lbl}:")
        for cat, d in agg["per_category"].get(lbl, {}).items():
            note = "  (low conf)" if d["n"] < 3 else ""
            print(f"    {cat:14s}: {d['mark']} {d['mean']:.2f} ± {d['stdev']:.2f}, n={d['n']}{note}")

    return 1 if fails > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
