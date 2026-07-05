#!/usr/bin/env python3
"""生医扩展的离线自测（零网络、零代理）。CI 默认跑这个。

覆盖 phase-5 五点里能纯离线验证的部分：
  - fixture 回放层（replay 命中 / miss raise / 脱敏）
  - bio_eval tool_executor 能加载工具、dispatch、错误处理
  - 证据 linter 默认 JSON 不含 line_text、含 line_sha256（隐私）
  - generator golden（委托 test_generators_golden.py）

用法：
    python test/test_bio_offline.py
退出码非零 = 有断言失败。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

_ROOT = Path(__file__).resolve().parents[1]
_FIX = _ROOT / "test" / "generators" / "fixtures"
sys.path.insert(0, str(_ROOT / "packs"))

_fails = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        _fails.append(name)


def test_fixtures():
    print("[fixtures]")
    from _lib import fixtures, http
    fixtures.activate(_FIX, mode="replay")
    try:
        # HGNC EGFR 已录（td_druggability fixture）
        data = http.get_json("https://rest.genenames.org/fetch/symbol/EGFR",
                             headers={"Accept": "application/json"})
        docs = ((data or {}).get("response") or {}).get("docs") or []
        check("replay 命中 HGNC EGFR", bool(docs) and docs[0].get("symbol") == "EGFR")
        # 未录的 URL → replay 模式 raise FixtureMiss
        missed = False
        try:
            http.get_json("https://rest.genenames.org/fetch/symbol/NOSUCHGENE",
                         headers={"Accept": "application/json"})
        except fixtures.FixtureMiss:
            missed = True
        check("replay 未命中 raise FixtureMiss", missed)
        st = fixtures.stats()
        check("命中计数正确", st["hits"] >= 1)
    finally:
        fixtures.deactivate()

    # 脱敏：录制时敏感键被抹
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        fixtures.activate(td, mode="record")
        try:
            key = fixtures._key("GET", "https://x.example/a",
                                {"api_key": "SECRET123", "q": "test"}, None)
            fixtures.record("GET", "https://x.example/a",
                            {"api_key": "SECRET123", "q": "test"}, None, b'{"ok":1}')
            rec = json.loads((Path(td) / f"{key}.json").read_text("utf-8"))
            blob = json.dumps(rec)
            check("fixture 不含明文 key", "SECRET123" not in blob,
                  detail="录制脱敏失败")
            check("fixture params 有 redacted 标记", "<redacted>" in blob)
        finally:
            fixtures.deactivate()


def test_tool_executor():
    print("[tool_executor]")
    from _lib import fixtures
    sys.path.insert(0, str(_ROOT / "test" / "bio_eval"))
    fixtures.activate(_FIX, mode="replay")
    try:
        import tool_executor
        names = tool_executor.available_tool_names()
        check("加载了 >= 20 个工具", len(names) >= 20, detail=f"只有 {len(names)}")
        for n in ("search_articles", "search_trials", "compound_search", "evidence_verify"):
            check(f"工具名含 {n}", n in names)
        # 未知工具 → is_error，不 raise
        r = tool_executor.execute_tool("nonexistent_xyz", {})
        check("未知工具返回 is_error", r["is_error"] is True)
        # 错误参数 → is_error（不崩）
        r2 = tool_executor.execute_tool("search_articles", {"bad_param": 1})
        check("错误参数返回 is_error", r2["is_error"] is True)
    finally:
        fixtures.deactivate()


def test_linter_privacy():
    print("[linter privacy]")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        draft = Path(td) / "draft.md"
        draft.write_text("Patient John Doe MRN 12345, ref [PMID:99999999].\n", "utf-8")
        # 默认 JSON：无 line_text，有 line_sha256
        out = subprocess.run(
            [sys.executable, str(_ROOT / "packs" / "bio-audit" / "evidence_linter.py"),
             "--format", "json", str(draft)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**_env_replay()},
        )
        try:
            d = json.loads(out.stdout)
        except Exception:
            check("linter 默认 JSON 可解析", False, detail=out.stdout[:200] + out.stderr[:200])
            return
        findings = list(d.get("files", {}).values())[0] if d.get("files") else []
        check("默认 JSON 无 line_text", all("line_text" not in f for f in findings))
        check("默认 JSON 有 line_sha256", all("line_sha256" in f for f in findings) and bool(findings))
        check("默认 JSON 不泄露 MRN 原文", "12345" not in out.stdout and "John Doe" not in out.stdout)
        check("privacy note 存在", "_privacy" in d)

        # --include-line-text：显式导出
        out2 = subprocess.run(
            [sys.executable, str(_ROOT / "packs" / "bio-audit" / "evidence_linter.py"),
             "--format", "json", "--include-line-text", str(draft)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env={**_env_replay()},
        )
        d2 = json.loads(out2.stdout)
        f2 = list(d2.get("files", {}).values())[0]
        check("--include-line-text 才导出原文", any("line_text" in x for x in f2))
        check("include 模式 privacy note 含 PHI 警告", "PHI" in d2.get("_privacy", ""))


def _env_replay():
    import os
    e = dict(os.environ)
    e["CSSWITCH_HTTP_FIXTURES"] = str(_FIX)
    e["CSSWITCH_HTTP_FIXTURE_MODE"] = "replay"
    return e


def test_generators_golden():
    print("[generators golden]  (委托 test_generators_golden.py)")
    out = subprocess.run(
        [sys.executable, str(_ROOT / "test" / "generators" / "test_generators_golden.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    check("golden 全部通过", out.returncode == 0,
          detail=out.stdout[-200:] + out.stderr[-200:])


def test_evidence_profile():
    """需求 1：evidence_profile 从元数据抽物种/样本量/实验类型（纯函数，离线）。"""
    print("[evidence_profile]")
    from _lib import evidence_profile as ep
    rct = ep.build_profile({"exists": True, "title": "randomized phase II trial",
                            "abstract": "We enrolled 245 patients. metastatic disease.",
                            "mesh_terms": ["Humans", "Aged"], "evidence_type": "RCT",
                            "phase": "PHASE2"})
    check("人类物种识别", rct["species"]["value"] == "human")
    check("样本量抽取 n=245", rct["sample_size"]["n"] == 245)
    check("实验类型含临床 II 期", "II" in rct["experiment"]["label"])
    animal = ep.build_profile({"exists": True, "title": "mouse xenograft model",
                               "abstract": "murine", "mesh_terms": ["Animals", "Mice"],
                               "evidence_type": "unclassified"})
    check("动物物种识别", animal["species"]["value"] == "animal")


def test_evidence_graph_offline():
    """需求 1+2：evidence_graph 检出错配/反证，uncertainty_ledger 出五段（monkeypatch 网络）。"""
    print("[evidence_graph + uncertainty_ledger]")
    import importlib.util
    p = _ROOT / "packs" / "bio-audit" / "evidence_verify_server.py"
    spec = importlib.util.spec_from_file_location("av_offline", p)
    av = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(av)
    # 注意：PMID 形状校验要求 4-9 位数字，测试的假 ID 必须用合法形状
    fake = {"10000001": {"exists": True, "title": "human RCT", "abstract": "245 patients",
                         "mesh_terms": ["Humans"], "evidence_type": "RCT"},
            "10000002": {"exists": True, "title": "mouse study", "abstract": "murine",
                         "mesh_terms": ["Animals", "Mice"], "evidence_type": "unclassified"}}
    av._verify_pmid = lambda x: fake.get(x, {"exists": False})
    av._verify_doi = lambda x: {"exists": False}
    av._verify_nct = lambda x: {"exists": False}
    g = av.evidence_graph(claims=[
        {"text": "药物 X 在人类有效", "asserted": {"species": "human"},
         "refs": [{"id_type": "pmid", "id": "10000002", "stance": "supports"}]},
        {"text": "编造引用", "refs": [{"id_type": "pmid", "id": "99999999", "stance": "supports"}]},
    ])
    check("检出物种错配", any("错配" in c and "animal" in c
                             for cl in g["claims"] for c in cl["conflicts"]))
    check("检出不存在引用", g["summary"]["unsupported"] == 1)
    led = av.uncertainty_ledger(graph_claims=g["claims"])
    for sec in ("known_knowns", "known_unknowns", "conflicts", "missing_data", "next_experiment"):
        check(f"台账含 {sec}", sec in led["ledger"])


def test_question_compiler():
    """需求 3：compile_research_question 把模糊问题编译成结构化任务（离线）。"""
    print("[question_compiler]")
    import importlib.util
    p = _ROOT / "packs" / "bio-compiler" / "question_compiler_server.py"
    spec = importlib.util.spec_from_file_location("qc_offline", p)
    qc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qc)
    r = qc.compile_research_question(question="EGFR 在 GBM 里还有没有新靶点价值")
    check("识别原型=靶点验证", r["archetype"] == "target-validation")
    check("识别疾病=Glioblastoma", r["disease"].get("name") == "Glioblastoma")
    check("识别分子=EGFR", any(m["symbol"] == "EGFR" for m in r["molecules"]))
    check("推荐 skill=target-discovery", r["recommended_skill"] == "target-discovery")
    check("给出推荐工具链", len(r["recommended_toolchain"]) >= 3)


def test_bio_eval_rubric():
    """需求 4：bio_eval 多维 rubric 自检（子进程跑 run.py --selftest）。"""
    print("[bio_eval rubric selftest]  (委托 run.py --selftest)")
    out = subprocess.run(
        [sys.executable, str(_ROOT / "test" / "bio_eval" / "run.py"), "--selftest"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    check("rubric selftest 通过", out.returncode == 0,
          detail=out.stdout[-300:] + out.stderr[-200:])


def main() -> int:
    test_fixtures()
    test_tool_executor()
    test_linter_privacy()
    test_generators_golden()
    test_evidence_profile()
    test_evidence_graph_offline()
    test_question_compiler()
    test_bio_eval_rubric()
    print()
    if _fails:
        print(f"[test_bio_offline] {len(_fails)} 项失败：{', '.join(_fails)}")
        return 1
    print("[test_bio_offline] 全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
