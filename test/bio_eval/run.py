#!/usr/bin/env python3
"""生医回归测试 runner —— 真实 tool loop。

用法：
    python test/bio_eval/run.py --proxy http://127.0.0.1:18991/<secret>
    python test/bio_eval/run.py --proxy ... --cases pubmed,ctgov  # 只跑某类
    python test/bio_eval/run.py --summary   # 汇总所有历史结果，不打上游

设计（v2：完整 agent loop）：
  - 走 CSSwitch 代理链路（http://127.0.0.1:<port>/<secret>/v1/messages）
  - **完整多轮循环**：模型发 tool_use → tool_executor 真跑本地 MCP handler（fixture 激活时离线）
    → tool_result 回灌 → 模型继续 → 直到 end_turn 或达 max_turns
  - 最终答案跑 evidence_linter：校验答复里挂的 PMID / DOI / NCT 真实存在
  - 评分同时看：① 是否发起了正确的 tool_use ② 最终引用是否经得起 linter 校验
  - 结果写 `test/bio_eval/results/<label>-<ts>.json`

fixture：设 `CSSWITCH_HTTP_FIXTURES=<dir>` 让工具执行离线（CI 用）。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent))
from cases import CASES, cases_by_ids  # noqa: E402
from cases_data import counts_by_category  # noqa: E402
import rubric  # noqa: E402
import tool_executor  # noqa: E402


_THRESHOLDS = [
    ("✓✓", 0.9),
    ("✓",  0.7),
    ("⚠",  0.4),
    ("✗",  0.0),
]
_RESULTS_DIR = Path(__file__).parent / "results"


def _mark(score: float) -> str:
    for m, t in _THRESHOLDS:
        if score >= t:
            return m
    return "✗"


def _post_anthropic(proxy: str, payload: Dict[str, Any], timeout: float = 120.0) -> Dict[str, Any]:
    """向 proxy /v1/messages 打一发 Anthropic-format 请求，返回解析后的 JSON。"""
    url = proxy.rstrip("/") + "/v1/messages"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",  # 兼容标准头
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {
                "status": r.status,
                "body": json.loads(r.read().decode("utf-8", "replace")),
            }
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": e.read().decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        return {"status": 0, "error": str(e)}


def _extract_tool_calls(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 Anthropic 兼容响应里挖 tool_use blocks。"""
    body = resp.get("body")
    if not isinstance(body, dict):
        return []
    content = body.get("content") or []
    out = []
    for blk in content:
        if isinstance(blk, dict) and blk.get("type") == "tool_use":
            out.append({
                "name": blk.get("name"),
                "input": blk.get("input") or {},
                "id": blk.get("id"),
            })
    return out


def _extract_text(resp: Dict[str, Any]) -> str:
    body = resp.get("body")
    if not isinstance(body, dict):
        return str(body) if body is not None else ""
    content = body.get("content") or []
    parts = []
    for blk in content:
        if isinstance(blk, dict) and blk.get("type") == "text":
            parts.append(blk.get("text") or "")
    return "\n".join(parts)


def _assistant_content(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把上游响应的 content blocks 原样取出（含 text + tool_use），回灌下一轮。"""
    body = resp.get("body")
    if not isinstance(body, dict):
        return []
    return body.get("content") or []


def _lint_final_text(text: str) -> Dict[str, Any]:
    """对最终答复跑 evidence_linter：抽 PMID/DOI/NCT 并逐条校验真实性。
    返回 {n_total, n_exist, n_fake, details}。工具执行走 _lib/http（fixture 时离线）。"""
    import importlib.util
    # 包名带连字符（bio-audit），只能按文件路径加载。仓库根 = parents[2]。
    p = Path(__file__).resolve().parents[2] / "packs" / "bio-audit" / "evidence_linter.py"
    if not p.is_file():
        return {"n_total": 0, "n_exist": 0, "n_fake": 0, "details": [], "note": "linter 不可用"}
    spec = importlib.util.spec_from_file_location("bioeval_linter", p)
    lint = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(lint)  # type: ignore

    # 直接复用 linter 的行扫描 + verify（对着字符串而非文件）
    findings = []
    for line_no, line in enumerate(text.splitlines(), 1):
        findings.extend(lint._scan_line(line, line_no))
    n_exist = n_fake = 0
    details = []
    for f in findings:
        try:
            if f.id_type == "pmid":
                meta = lint._verify_pmid(f.id)
            elif f.id_type == "doi":
                meta = lint._verify_doi(f.id)
            elif f.id_type == "nct":
                meta = lint._verify_nct(f.id)
            else:
                meta = {"exists": False}
        except Exception as e:  # noqa: BLE001
            meta = {"exists": False, "error": str(e)}
        exists = bool(meta.get("exists"))
        if exists:
            n_exist += 1
        else:
            n_fake += 1
        details.append({"id_type": f.id_type, "id": f.id, "exists": exists})
    return {"n_total": len(findings), "n_exist": n_exist, "n_fake": n_fake, "details": details}


def run_case(proxy: str, case: Dict[str, Any], model: str,
             max_turns: int = 6, run_linter: bool = True) -> Dict[str, Any]:
    """完整 agent loop：tool_use → 执行 → tool_result → 继续 → 最终答案 → linter。"""
    messages: List[Dict[str, Any]] = [
        {"role": "user", "content": case["prompt"]}
    ]
    base_payload = {"model": model, "max_tokens": case["max_tokens"]}
    if case.get("tools"):
        base_payload["tools"] = case["tools"]

    turns_log: List[Dict[str, Any]] = []
    all_tool_calls: List[Dict[str, Any]] = []
    observations: List[Dict[str, Any]] = []  # 工具返回，供 grounding 维度评分
    final_text = ""
    last_status = None

    for turn in range(max_turns):
        payload = dict(base_payload)
        payload["messages"] = messages
        # tool_choice 只在第一轮强制（若 case 指定）；后续轮让模型自由决定收尾
        if turn == 0 and case.get("tool_choice") and case["tool_choice"] != "auto":
            payload["tool_choice"] = case["tool_choice"]
        resp = _post_anthropic(proxy, payload)
        last_status = resp.get("status")
        if last_status != 200:
            return {
                "id": case["id"], "category": case["category"],
                "verdict": "profile_error",
                "reason": f"turn {turn}: upstream {last_status} — "
                          f"{str(resp.get('body') or resp.get('error'))[:200]}",
                "score": None,
            }
        content = _assistant_content(resp)
        tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        text_this = _extract_text(resp)
        if text_this:
            final_text = text_this
        for tu in tool_uses:
            all_tool_calls.append({"name": tu.get("name"), "input": tu.get("input")})

        if not tool_uses:
            # 模型不再调工具 → 收尾
            turns_log.append({"turn": turn, "text": text_this[:200], "tool_uses": 0})
            break

        # 执行每个 tool_use，产出 tool_result 回灌
        messages.append({"role": "assistant", "content": content})
        tool_results = []
        for tu in tool_uses:
            r = tool_executor.execute_tool(tu.get("name"), tu.get("input") or {})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.get("id"),
                "content": r["content"],
                "is_error": r["is_error"],
            })
            observations.append({"name": tu.get("name"), "content": r["content"]})
        messages.append({"role": "user", "content": tool_results})
        turns_log.append({
            "turn": turn,
            "tool_uses": [tu.get("name") for tu in tool_uses],
            "text": text_this[:120],
        })
    else:
        turns_log.append({"turn": max_turns, "note": "达到 max_turns 上限，未自然收尾"})

    # linter：最终答复里的引用是否真实
    lint_result = _lint_final_text(final_text) if run_linter else None

    # 多维评分（rubric）：工具调用 + 结果被正确使用（grounding）+ 证据支持（linter）
    #                    + 是否暴露不确定性 + 反幻觉乘法惩罚
    ctx = {
        "final_text": final_text,
        "tool_calls": all_tool_calls,
        "tool_results": observations,
        "n_turns": len(turns_log),
        "lint": lint_result or {},
    }
    scored = rubric.score_case(case, ctx)
    final_score = scored["score"]

    return {
        "id": case["id"], "category": case["category"],
        "verdict": _mark(final_score), "score": final_score,
        "base_score": scored["base_score"],
        "dims": scored["dims"],
        "fake_ratio": scored["fake_ratio"],
        "notes": scored["notes"],
        "n_turns": len(turns_log),
        "tool_calls_seen": all_tool_calls,
        "final_text_preview": final_text[:300],
        "lint": lint_result,
        "turns": turns_log,
        "upstream_status": last_status,
    }


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_cat: Dict[str, List[float]] = {}
    for r in results:
        if r.get("score") is None:
            continue
        by_cat.setdefault(r["category"], []).append(r["score"])
    cat_scores = {c: round(sum(v) / len(v), 3) for c, v in by_cat.items()}
    overall = round(sum(cat_scores.values()) / len(cat_scores), 3) if cat_scores else 0.0
    return {
        "by_category": cat_scores,
        "by_category_mark": {c: _mark(s) for c, s in cat_scores.items()},
        "overall": overall,
        "overall_mark": _mark(overall),
        "n_profile_errors": sum(1 for r in results if r.get("verdict") == "profile_error"),
    }


def selftest() -> int:
    """离线自检：不打上游，用合成 ctx 验证 rubric 各维度打分符合预期。CI 可跑。"""
    import cases as _cases
    by_id = {c["id"]: c for c in _cases.CASES}
    checks: List[tuple] = [
        # (case_id, ctx, 断言函数, 说明)
        ("lit_metformin_cv_meta",
         {"final_text": "找到了 PMID:29127598。", "n_turns": 2,
          "tool_calls": [{"name": "search_articles", "input": {"query": "metformin cardiovascular"}}],
          "tool_results": [{"name": "search_articles", "content": "results: PMID 29127598 ..."}],
          "lint": {"n_total": 1, "n_exist": 1, "n_fake": 0}},
         lambda s: s["score"] >= 0.9, "调对工具+query 相关+ID grounded → 高分"),
        ("lit_metformin_cv_meta",
         {"final_text": "我记得答案是 PMID:12345678。", "n_turns": 1,
          "tool_calls": [], "tool_results": [],
          "lint": {"n_total": 1, "n_exist": 0, "n_fake": 1}},
         lambda s: s["score"] <= 0.2, "没调工具+编造 ID → 门控+幻觉惩罚 → 低分"),
        ("ea_catch_fake",
         {"final_text": "校验后 PMID:99999999 不存在，撤回该结论。", "n_turns": 2,
          "tool_calls": [{"name": "evidence_verify", "input": {}}],
          "tool_results": [{"name": "evidence_verify", "content": "exists=false"}],
          "lint": {"n_total": 1, "n_exist": 0, "n_fake": 1,
                   "details": [{"id_type": "pmid", "id": "99999999", "exists": False}]}},
         lambda s: s["dims"].get("tool_invoked") == 1.0 and s["score"] >= 0.7,
         "调 evidence_verify 且正确点名假 ID 撤回 → 不被幻觉惩罚（expected_fake_ids）"),
        ("json_evidence_table",
         {"final_text": '```json\n{"claims":[{"claim":"a","refs":[],"verdict":"supported"}]}\n```',
          "n_turns": 1, "tool_calls": [], "tool_results": [], "lint": {}},
         lambda s: s["dims"].get("json_valid", 0) >= 0.9, "合法 JSON+shape 对 → json_valid 高"),
        ("json_evidence_table",
         {"final_text": "这是证据表：claim1 supported，我就不给 JSON 了。",
          "n_turns": 1, "tool_calls": [], "tool_results": [], "lint": {}},
         lambda s: s["dims"].get("json_valid", 1) == 0.0, "无法解析 JSON → json_valid=0"),
        ("lit_synthesis_uncertainty",
         {"final_text": "综述...\nKnown knowns:..\nKnown unknowns:..\nConflicts:..\n"
                        "Missing data:..\nNext experiment:..\nPMID:29127598",
          "n_turns": 2,
          "tool_calls": [{"name": "search_articles", "input": {"query": "vitamin D cancer"}}],
          "tool_results": [{"name": "search_articles", "content": "PMID 29127598"}],
          "lint": {"n_total": 1, "n_exist": 1, "n_fake": 0}},
         lambda s: s["dims"].get("uncertainty") == 1.0, "五段面板齐全 → uncertainty=1"),
    ]
    ok = True
    for cid, ctx, assertion, desc in checks:
        case = by_id.get(cid)
        if not case:
            print(f"  ✗ 找不到 case {cid}")
            ok = False
            continue
        s = rubric.score_case(case, ctx)
        passed = bool(assertion(s))
        ok = ok and passed
        mark = "✓" if passed else "✗"
        print(f"  {mark} {cid:26s} score={s['score']:.2f} dims={s['dims']} — {desc}")
    print(f"\n[bio_eval] rubric selftest {'PASS' if ok else 'FAIL'}；"
          f"case 总数 {len(_cases.CASES)}，分类：{counts_by_category()}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", help="代理 URL：http://127.0.0.1:PORT/SECRET")
    ap.add_argument("--model", default="claude-opus-4-8",
                    help="模型 id（代理会 map 到当前 profile 的实际模型）")
    ap.add_argument("--cases", help="逗号分隔的 case id / category")
    ap.add_argument("--label", default="", help="结果文件标签（一般填 profile 名）")
    ap.add_argument("--summary", action="store_true", help="只汇总已有结果，不打上游")
    ap.add_argument("--list", action="store_true", help="列出所有 case（按类），不打上游")
    ap.add_argument("--selftest", action="store_true", help="离线自检 rubric（不打上游）")
    ap.add_argument("--write-to-config", action="store_true",
                    help="把 per-category 得分写回 ~/.csswitch/config.json 的 probe_results")
    ap.add_argument("--max-turns", type=int, default=6, help="tool loop 最大轮数")
    ap.add_argument("--no-linter", action="store_true", help="跳过最终答复的引用 linter 校验")
    args = ap.parse_args()

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.selftest:
        return selftest()

    if args.list:
        print(f"[bio_eval] 共 {len(CASES)} case，{len(counts_by_category())} 类：")
        for cat, n in counts_by_category().items():
            print(f"  {cat:18s}: {n}")
            for c in CASES:
                if c["category"] == cat:
                    print(f"      - {c['id']}")
        return 0

    if args.summary:
        # 汇总所有历史结果
        files = sorted(_RESULTS_DIR.glob("*.json"))
        if not files:
            print("[bio_eval] 无历史结果。先跑 --proxy 版本。")
            return 0
        for f in files:
            data = json.loads(f.read_text("utf-8"))
            print(f"=== {f.name} ===")
            print(f"  overall: {data['summary']['overall_mark']} ({data['summary']['overall']})")
            for cat, score in (data["summary"]["by_category"] or {}).items():
                print(f"    {cat:12s}: {_mark(score)} ({score})")
        return 0

    if not args.proxy:
        print("[bio_eval] 缺 --proxy。用法见 test/bio_eval/README.md")
        return 2

    selected = cases_by_ids(args.cases.split(",") if args.cases else None)
    if not selected:
        print("[bio_eval] --cases 匹配到 0 个 case")
        return 2

    print(f"[bio_eval] 跑 {len(selected)} 个 case，proxy={args.proxy}")
    results: List[Dict[str, Any]] = []
    for c in selected:
        print(f"  ▶ {c['id']:20s}", end=" ", flush=True)
        r = run_case(args.proxy, c, args.model,
                     max_turns=args.max_turns, run_linter=not args.no_linter)
        results.append(r)
        if r.get("score") is None:
            print(f"[{r['verdict']}] {r.get('reason', '')[:80]}")
        else:
            lint = r.get("lint") or {}
            fake = f" fake={lint.get('n_fake')}/{lint.get('n_total')}" if lint.get("n_total") else ""
            dims = r.get("dims") or {}
            dims_s = " ".join(f"{k}={v}" for k, v in dims.items())
            print(f"[{r['verdict']}] score={r['score']:.2f} turns={r.get('n_turns')}{fake}  [{dims_s}]")

    summary = summarize(results)
    label = args.label or "unlabeled"
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = _RESULTS_DIR / f"{label}-{ts}.json"
    out_path.write_text(json.dumps({
        "ts": ts, "label": label, "proxy": args.proxy, "model": args.model,
        "results": results, "summary": summary,
    }, ensure_ascii=False, indent=2), "utf-8")
    os.chmod(out_path, 0o600)
    print(f"\n[bio_eval] 结果写入 {out_path}")
    print(f"[bio_eval] overall: {summary['overall_mark']} ({summary['overall']})")
    for cat, score in summary["by_category"].items():
        print(f"  {cat:12s}: {_mark(score)} ({score})")

    if args.write_to_config:
        home = os.environ.get("HOME")
        if not home:
            print("[bio_eval] 缺 HOME 环境变量，跳过 --write-to-config")
            return 0
        cfg_path = Path(home) / ".csswitch" / "config.json"
        if not cfg_path.is_file():
            print(f"[bio_eval] 找不到 {cfg_path}，跳过 --write-to-config")
            return 0
        cfg = json.loads(cfg_path.read_text("utf-8"))
        cfg.setdefault("probe_results", {})
        active_id = cfg.get("active_id") or "unknown"
        for cat, score in summary["by_category"].items():
            key = f"{active_id}:bio_eval_{cat}"
            cfg["probe_results"][key] = json.dumps({
                "verdict": _mark(score), "reason": f"bio_eval score={score}",
                "score": score, "ts": ts,
            }, ensure_ascii=False)
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
        os.chmod(cfg_path, 0o600)
        print(f"[bio_eval] 已写回 {cfg_path}（probe_results）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
