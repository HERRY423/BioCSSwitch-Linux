#!/usr/bin/env python3
"""生物医学研究问题编译器 MCP。

把一个模糊的自然语言问题（"EGFR 在 GBM 里还有没有新靶点价值"）**编译**成一份
结构化研究任务书：研究对象 / 疾病 / 分子 / 干预 / 终点 / 数据库 / 排除标准 /
证据等级门槛 / 推荐工具链 / 该进哪个 workflow skill。

设计原则（和整个项目一致）：
  1. **确定性、可核对**。每个字段都能指到"凭哪条规则得到"（via 字段）。识别不到就标
     unknown / needs_user_input，绝不编。
  2. **不代替用户拍板**。编译结果是"给用户确认的任务书草案"——skill 会把它读给用户，
     缺口（排除标准、干预、终点细化）由用户补齐后才往下走。
  3. **直接接到既有工具链**。toolchain 里的工具名都是本项目真实存在的 MCP / 生成器，
     不虚构工具。

对外工具：
  compile_research_question — 主编译器
  compiler_capabilities     — 自述能识别哪些实体 / 原型（透明度，便于用户判断覆盖范围）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # packs/ → 找得到 _lib
sys.path.insert(0, str(Path(__file__).resolve().parent))      # 本目录 → 找得到 compiler_lexicon

from _lib.server import MCPServer  # noqa: E402

import compiler_lexicon as lex  # noqa: E402


server = MCPServer("bio-compiler", "0.1.0")


def _pick_research_object(genes, drugs, diseases) -> Dict[str, Any]:
    """研究对象 = 最主要的分子/药物 + 疾病组合。"""
    obj: Dict[str, Any] = {}
    if genes:
        obj["molecule"] = genes[0]["symbol"]
        obj["molecule_type"] = "gene/protein"
        obj["molecule_confidence"] = genes[0]["confidence"]
    elif drugs:
        obj["molecule"] = drugs[0]["name"]
        obj["molecule_type"] = "drug/compound"
        obj["molecule_confidence"] = drugs[0]["confidence"]
    if diseases:
        obj["disease"] = diseases[0]["name"]
    return obj


def _suggest_exclusions(diseases, archetype) -> List[str]:
    out = ["物种：默认仅人类证据下结论；临床前（动物/体外）证据须显式标注、不外推",
           "语言：若只纳英文文献，中文/日文文献可能漏检——需显式声明"]
    areas = {d.get("area") for d in diseases if d.get("area")}
    if "oncology" in areas:
        out.append("肿瘤类型：区分组织学亚型/分子分型，避免把泛癌结论套到单一癌种")
        out.append("线数/分期：区分一线 vs 后线、早期 vs 转移，疗效不可跨线数外推")
    if archetype in ("efficacy-comparison", "safety"):
        out.append("研究设计：优先 RCT / 前瞻队列；回顾性/单臂研究降级或单列")
    if archetype == "target-validation":
        out.append("证据来源：把 text-mining co-mention 与功能实验/临床关联分开计权")
    return out


@server.tool(
    "compile_research_question",
    "Compile a vague biomedical question (e.g. 'does EGFR still have new target value in GBM?') "
    "into a STRUCTURED research task: research object, disease, molecule, intervention, endpoints, "
    "databases, exclusion criteria, evidence bar, recommended toolchain, and which workflow skill "
    "to enter. Deterministic & auditable — every field records how it was derived; unresolved "
    "fields are flagged needs_user_input rather than guessed. Run this FIRST on any open-ended "
    "research question before searching.",
    {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The raw, possibly vague research question"},
            "language": {"type": "string", "enum": ["zh", "en"], "default": "zh"},
        },
        "required": ["question"],
    },
)
def compile_research_question(question: str, language: str = "zh"):
    q = question or ""
    genes = lex.detect_genes(q)
    drugs = lex.detect_drugs(q)
    diseases = lex.detect_diseases(q)
    archetype, arch_hits = lex.detect_archetype(q)
    route = lex.ROUTES.get(archetype, lex.ROUTES["unknown"])

    research_object = _pick_research_object(genes, drugs, diseases)

    # 干预：优先用户提到的药物；否则按原型给"待定"提示
    if drugs:
        intervention = {"value": drugs[0]["name"], "via": "detected-drug"}
    elif archetype in ("target-validation", "drug-repurposing"):
        intervention = {"value": None,
                        "needs_user_input": "未指定干预方式（抑制剂 / 抗体 / ADC / 降解剂 / 细胞疗法？）——"
                                            "靶点价值高度依赖成药方式，需先明确"}
    else:
        intervention = {"value": None, "needs_user_input": "问题未含明确干预，请补充"}

    # 缺口检查
    gaps: List[str] = []
    if not diseases:
        gaps.append("未识别到疾病 —— 请提供规范疾病名（或让 disambiguate 归一）")
    if not genes and not drugs:
        gaps.append("未识别到分子/药物 —— 请确认研究对象")
    if archetype == "unknown":
        gaps.append("问题原型未识别（靶点验证/老药新用/标志物/机制/疗效/流行病学/安全性）—— 请澄清目标")
    if any(g.get("confidence") == "candidate" for g in genes):
        gaps.append("部分基因符号仅按形状猜测，建议用 disambiguate 确认")

    compiled = {
        "raw_question": q,
        "archetype": archetype,
        "archetype_signals": arch_hits,
        "research_object": research_object or {"needs_user_input": "研究对象不明"},
        "disease": (diseases[0] if diseases else {"needs_user_input": "疾病不明"}),
        "all_diseases": diseases,
        "molecules": genes,
        "drugs": drugs,
        "intervention": intervention,
        "endpoints": route["endpoints"],
        "databases": route["databases"],
        "exclusion_criteria": _suggest_exclusions(diseases, archetype),
        "evidence_bar": route["evidence_bar"],
        "recommended_toolchain": [{"tool": t, "purpose": p} for t, p in route["toolchain"]],
        "recommended_skill": route["skill"],
        "gaps": gaps,
        "note": "这是任务书草案：请先与用户确认 gaps 与 intervention，再按 recommended_toolchain 执行；"
                "结论阶段必须走 evidence_graph + uncertainty_ledger。",
    }
    return compiled


@server.tool(
    "compiler_capabilities",
    "List what the question compiler can currently recognize (disease abbreviations, known targets, "
    "drug patterns, question archetypes). Transparency tool so the user knows coverage limits.",
    {"type": "object", "properties": {}},
)
def compiler_capabilities():
    return {
        "disease_abbreviations": sorted(lex.DISEASE_ABBR.keys()),
        "disease_zh_aliases": sorted(lex.DISEASE_ZH.keys()),
        "known_targets_count": len(lex.KNOWN_TARGETS),
        "drug_suffixes": list(lex.DRUG_SUFFIX),
        "archetypes": [a for a, _ in lex.ARCHETYPES] + ["unknown"],
        "note": "识别是启发式：疾病缩写/中文别名靠词表，基因靠形状+已知靶点集，药物靠后缀+已知药名。"
                "未覆盖的实体会标 candidate / needs_user_input，交给 disambiguate 或用户确认。",
    }


if __name__ == "__main__":
    server.run()
