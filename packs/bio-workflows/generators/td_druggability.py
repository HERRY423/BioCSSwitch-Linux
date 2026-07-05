#!/usr/bin/env python3
"""靶点 druggability 评分卡生成器。

结合 UniProt / ChEMBL / Open Targets 的多维证据，为一个靶点产出一张评分卡：
  - Structural class（enzyme / GPCR / TF / scaffold / ...）
  - Known modulators in ChEMBL（有多少 active compound）
  - Approved drugs on the target
  - Ligand druggability heuristic（结构类别启发式）
  - Open Targets tractability（若可）
  - 一个综合评级 A/B/C/D

**这不是 LLM 的评级**——每一项都指向具体数据源和 URL，方便人工核对。

CLI：
    python packs/bio-workflows/generators/td_druggability.py --symbol BRCA1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _lib import http  # noqa: E402


_HGNC = "https://rest.genenames.org"
_UNIPROT = "https://rest.uniprot.org/uniprotkb"
_CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"
_OT_GQL = "https://api.platform.opentargets.org/api/v4/graphql"


# 启发式：结构类 → druggability 一档
_DRUGGABLE_CLASSES = {
    "high": {"enzyme", "kinase", "protease", "phosphatase", "ion channel", "gpcr",
             "g-protein coupled receptor", "nuclear receptor", "transporter",
             "oxidoreductase", "hydrolase", "transferase"},
    "medium": {"protein-protein interaction", "receptor", "chaperone",
               "membrane protein", "atpase"},
    "low": {"transcription factor", "scaffold protein", "ribosomal protein",
            "intrinsically disordered", "histone"},
}


def _classify_druggability(text: str) -> str:
    if not text:
        return "unknown"
    lower = text.lower()
    for level in ("high", "medium", "low"):
        for kw in _DRUGGABLE_CLASSES[level]:
            if kw in lower:
                return level
    return "unknown"


def _hgnc(symbol: str) -> Dict[str, Any]:
    try:
        data = http.get_json(f"{_HGNC}/fetch/symbol/{symbol}",
                             headers={"Accept": "application/json"})
        docs = ((data or {}).get("response") or {}).get("docs") or []
        if not docs:
            return {}
        return docs[0]
    except Exception:
        return {}


def _uniprot(accession: str) -> Dict[str, Any]:
    try:
        return http.get_json(f"{_UNIPROT}/{accession}.json") or {}
    except Exception:
        return {}


def _chembl_target(gene_symbol: str) -> Dict[str, Any]:
    try:
        data = http.get_json(f"{_CHEMBL}/target/search.json",
                             params={"q": gene_symbol, "limit": 5})
        return (data or {}).get("targets", [{}])[0] if (data or {}).get("targets") else {}
    except Exception:
        return {}


def _chembl_activity_count(target_chembl_id: str) -> Optional[int]:
    if not target_chembl_id:
        return None
    try:
        data = http.get_json(f"{_CHEMBL}/activity.json",
                             params={"target_chembl_id": target_chembl_id,
                                     "pchembl_value__gte": 6, "limit": 1, "format": "json"})
        return (data or {}).get("page_meta", {}).get("total_count")
    except Exception:
        return None


def _ot_target(ensembl_id: str) -> Dict[str, Any]:
    q = """
    query t($id: String!) {
      target(ensemblId: $id) {
        id approvedSymbol approvedName
        tractability { modality label value }
        knownDrugs(size: 50) { count uniqueDrugs uniqueTargets rows {
          drug { id name maximumClinicalTrialPhase approvedIndications }
        }}
      }
    }
    """
    try:
        return http.post_json(_OT_GQL, {"query": q, "variables": {"id": ensembl_id}}) or {}
    except Exception:
        return {}


def evaluate(symbol: str) -> Dict[str, Any]:
    """把整套证据合并到一张评分卡。"""
    hgnc = _hgnc(symbol)
    if not hgnc:
        return {"symbol": symbol, "found": False,
                "reason": f"HGNC 中未找到 {symbol}（可能是别名 / 已弃用）"}

    uniprot_ids = hgnc.get("uniprot_ids") or []
    uniprot_data = _uniprot(uniprot_ids[0]) if uniprot_ids else {}

    ensembl_id = hgnc.get("ensembl_gene_id") or ""

    # UniProt 结构类别文本（用 protein family / keyword）
    keywords = " ".join([k.get("name", "") for k in uniprot_data.get("keywords") or []])
    family_text = ""
    for c in uniprot_data.get("comments") or []:
        if c.get("commentType") == "SIMILARITY":
            for t in c.get("texts") or []:
                family_text += " " + (t.get("value") or "")
    druggability_class = _classify_druggability(keywords + " " + family_text)

    # ChEMBL：活性化合物数（pChEMBL ≥ 6，即 Ki ≤ 1μM）
    chembl_tgt = _chembl_target(symbol)
    chembl_id = chembl_tgt.get("target_chembl_id") or ""
    activity_count = _chembl_activity_count(chembl_id)

    # Open Targets：tractability + known drugs
    ot = _ot_target(ensembl_id).get("data", {}).get("target", {}) if ensembl_id else {}
    known_drugs = ot.get("knownDrugs", {}) or {}
    tract = ot.get("tractability") or []

    # 综合评级：可解释的启发式
    grade = _grade(druggability_class, activity_count, known_drugs.get("uniqueDrugs"),
                   tract)

    return {
        "symbol": symbol, "found": True,
        "hgnc_id": hgnc.get("hgnc_id"),
        "name": hgnc.get("name"),
        "uniprot": {
            "accession": uniprot_ids[0] if uniprot_ids else None,
            "keywords_head": keywords[:200],
        },
        "ensembl_id": ensembl_id,
        "druggability_class": druggability_class,
        "druggability_class_evidence": (keywords + " " + family_text).strip()[:300],
        "chembl": {
            "target_chembl_id": chembl_id,
            "pref_name": chembl_tgt.get("pref_name"),
            "active_compounds_pchembl_6": activity_count,
        },
        "open_targets": {
            "unique_drugs": known_drugs.get("uniqueDrugs"),
            "drug_count": known_drugs.get("count"),
            "tractability_flags": [{"modality": t.get("modality"), "label": t.get("label"),
                                     "value": t.get("value")} for t in tract if t.get("value")],
        },
        "verdict": {
            "grade": grade["grade"],
            "rationale": grade["rationale"],
        },
    }


def _grade(dclass: str, activity: Optional[int], drugs: Optional[int],
           tract: List[Dict[str, Any]]) -> Dict[str, Any]:
    """启发式评级。可解释、可挑战。"""
    reasons = []
    score = 0
    # dclass
    if dclass == "high":
        score += 3; reasons.append("结构类别通常 druggable (+3)")
    elif dclass == "medium":
        score += 2; reasons.append("结构类别中等 druggability (+2)")
    elif dclass == "low":
        score += 0; reasons.append("结构类别通常难 druggable (0)")
    else:
        score += 1; reasons.append("结构类别未定 (+1)")
    # ChEMBL activity
    if activity is not None:
        if activity >= 100:
            score += 3; reasons.append(f"ChEMBL 里 ≥100 个 pChEMBL≥6 化合物 (+3)")
        elif activity >= 10:
            score += 2; reasons.append(f"ChEMBL 里 {activity} 个 pChEMBL≥6 化合物 (+2)")
        elif activity >= 1:
            score += 1; reasons.append(f"ChEMBL 里 {activity} 个化合物 (+1)")
        else:
            reasons.append("ChEMBL 里无活性化合物 (0)")
    # Approved drugs
    if drugs and drugs > 0:
        score += 3; reasons.append(f"Open Targets 已知 {drugs} 个药物 (+3)")
    # Tractability flags
    flags = sum(1 for t in tract if t.get("value"))
    if flags >= 3:
        score += 2; reasons.append(f"Open Targets tractability 命中 {flags} 项 (+2)")
    elif flags >= 1:
        score += 1; reasons.append(f"Open Targets tractability 命中 {flags} 项 (+1)")

    # 8 分制映射到 A/B/C/D
    if score >= 8: grade = "A"
    elif score >= 6: grade = "B"
    elif score >= 4: grade = "C"
    else: grade = "D"
    return {"grade": grade, "score_raw": score, "rationale": reasons}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, help="Gene symbol, e.g. BRCA1")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    r = evaluate(args.symbol)
    if args.format == "json":
        json.dump(r, sys.stdout, ensure_ascii=False, indent=2, default=str)
        return 0

    if not r.get("found"):
        print(r.get("reason") or "未找到")
        return 2

    print(f"═══ Druggability 评分卡：{r['symbol']} ═══")
    print(f"  HGNC: {r['hgnc_id']}  |  UniProt: {r['uniprot']['accession']}  "
          f"|  Ensembl: {r['ensembl_id']}")
    print(f"  Name: {r['name']}")
    print()
    print(f"  Druggability class      : {r['druggability_class']}")
    print(f"    (evidence excerpt: {r['druggability_class_evidence'][:120]})")
    print(f"  ChEMBL target ID        : {r['chembl']['target_chembl_id']}")
    print(f"    active compounds (pChEMBL≥6): {r['chembl']['active_compounds_pchembl_6']}")
    print(f"  Open Targets unique drugs: {r['open_targets']['unique_drugs']}")
    print(f"  Tractability flags       : "
          f"{len(r['open_targets']['tractability_flags'])} 项")
    print()
    v = r["verdict"]
    print(f"  ★★★ 综合评级：{v['grade']} ★★★")
    for line in v["rationale"]:
        print(f"    · {line}")
    print()
    print("  链接（用于人工核对）：")
    if r["uniprot"]["accession"]:
        print(f"    UniProt: https://www.uniprot.org/uniprotkb/{r['uniprot']['accession']}")
    if r["chembl"]["target_chembl_id"]:
        print(f"    ChEMBL:  https://www.ebi.ac.uk/chembl/target_report_card/{r['chembl']['target_chembl_id']}")
    if r["ensembl_id"]:
        print(f"    Open Targets: https://platform.opentargets.org/target/{r['ensembl_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
