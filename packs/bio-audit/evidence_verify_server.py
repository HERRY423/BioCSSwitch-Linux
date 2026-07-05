#!/usr/bin/env python3
"""证据审计 MCP：把「模型说的」和「真实存在的文献」对上。

工具：
  evidence_verify        — 一次校验一批 claim + 引用，返回 exists / metadata / warnings
  evidence_classify      — 按 PMID 归一化到 meta-analysis / RCT / cohort / ...
  evidence_build_table   — 一次产出证据表（Markdown），bio-audit skill 直接把它塞进最终答复

三条设计原则（bio-audit 的核心价值就在这几条）：
  1. **不存在就是不存在**。PMID/DOI/NCT 只要上游 404，标 `exists=false`，绝不猜「可能是笔误」，
     绝不建议 LLM 换个类似的 ID —— 那反而会诱导幻觉。
  2. **证据类型只从上游元数据推**（PubMed MeSH publication_type / CT.gov study_type），
     不从标题/摘要猜 —— 标题里带 randomized 也不代表就是 RCT。
  3. **不改结论，只做审计**。工具产出「审计报告」，模型自己决定撤回还是保留 —— 但审计报告
     本身会作为对话上下文出现，模型再输出未过审的结论就要承担明显的一致性代价。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import entrez, http  # noqa: E402
from _lib import evidence_profile as _ep  # noqa: E402
from _lib.cache import memoize  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-audit-verify", "0.1.0")

_CROSSREF = "https://api.crossref.org/works"
_CTGOV_V2 = "https://clinicaltrials.gov/api/v2/studies"

_PMID_RE = re.compile(r"^\d{4,9}$")
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
_NCT_RE = re.compile(r"^NCT\d{8}$", re.I)


def _normalize_id(id_type: str, ident: str) -> str:
    ident = (ident or "").strip()
    t = (id_type or "").lower()
    if t == "pmid":
        return ident.lstrip("PMID:").strip()
    if t == "doi":
        low = ident.lower()
        if low.startswith("doi:"):
            ident = ident[4:]
        if low.startswith("https://doi.org/"):
            ident = ident.split("https://doi.org/", 1)[1]
        return ident
    if t == "nct":
        return ident.upper()
    return ident


def _validate_shape(id_type: str, ident: str) -> Optional[str]:
    t = (id_type or "").lower()
    if t == "pmid" and not _PMID_RE.match(ident):
        return "PMID 应为 4-9 位数字"
    if t == "doi" and not _DOI_RE.match(ident):
        return "DOI 应形如 10.xxxx/yyy"
    if t == "nct" and not _NCT_RE.match(ident):
        return "NCT 应形如 NCT + 8 位数字"
    return None


# ---------- 三种源的最小校验器 ----------

@memoize("audit_pmid", ttl_seconds=7 * 24 * 3600)
def _verify_pmid(pmid: str) -> Dict[str, Any]:
    xml = entrez.efetch_text("pubmed", [pmid], rettype="abstract", retmode="xml")
    parsed = entrez.parse_pubmed_xml(xml)
    if not parsed:
        return {"exists": False}
    a = parsed[0]
    return {
        "exists": True,
        "title": a["title"],
        "authors": a["authors"],
        "journal": a["journal"],
        "year": a["year"],
        "doi": a["doi"],
        "evidence_type": a["evidence_type"],
        "publication_types": a["publication_types"],
        "mesh_terms": a.get("mesh_terms") or [],
        "abstract": a["abstract"],
    }


@memoize("audit_doi", ttl_seconds=30 * 24 * 3600)
def _verify_doi(doi: str) -> Dict[str, Any]:
    try:
        data = http.get_json(f"{_CROSSREF}/{doi}", params={"mailto": "csswitch@localhost.invalid"})
    except Exception as e:  # noqa: BLE001
        return {"exists": False, "error": str(e)}
    msg = (data or {}).get("message") or {}
    if not msg:
        return {"exists": False}
    title = (msg.get("title") or [""])[0]
    ctitle = (msg.get("container-title") or [""])[0]
    year = None
    for k in ("published-print", "published-online", "issued", "created"):
        v = msg.get(k)
        if v and v.get("date-parts"):
            year = v["date-parts"][0][0]
            break
    authors = [f"{a.get('family','')}, {a.get('given','')}".strip(", ")
               for a in (msg.get("author") or [])]
    return {
        "exists": True,
        "title": title,
        "journal": ctitle,
        "year": year,
        "authors": authors[:10],
        "type": msg.get("type"),
        "publisher": msg.get("publisher"),
    }


_CTGOV_TYPE_TO_EV = {
    # Study Type / Phase 归一化到项目证据等级
    "INTERVENTIONAL": "clinical-trial",
    "OBSERVATIONAL": "observational",
    "EXPANDED_ACCESS": "clinical-trial",
}


@memoize("audit_nct", ttl_seconds=7 * 24 * 3600)
def _verify_nct(nct: str) -> Dict[str, Any]:
    try:
        data = http.get_json(f"{_CTGOV_V2}/{nct}", params={"format": "json"})
    except Exception as e:  # noqa: BLE001
        return {"exists": False, "error": str(e)}
    prot = ((data or {}).get("protocolSection") or {})
    if not prot:
        return {"exists": False}
    ident = prot.get("identificationModule") or {}
    status = prot.get("statusModule") or {}
    design = prot.get("designModule") or {}
    enroll = design.get("enrollmentInfo") or {}
    study_type = design.get("studyType")
    return {
        "exists": True,
        "nct_id": ident.get("nctId"),
        "title": ident.get("briefTitle"),
        "official_title": ident.get("officialTitle"),
        "overall_status": status.get("overallStatus"),
        "start_date": (status.get("startDateStruct") or {}).get("date"),
        "completion_date": (status.get("completionDateStruct") or {}).get("date"),
        "phase": (design.get("phases") or [None])[0],
        "study_type": study_type,
        "enrollment": enroll.get("count"),
        "allocation": (design.get("designInfo") or {}).get("allocation"),
        "primary_purpose": (design.get("designInfo") or {}).get("primaryPurpose"),
        "evidence_type": _CTGOV_TYPE_TO_EV.get((study_type or "").upper(), "clinical-trial"),
    }


def _verify_ref(id_type: str, ident_raw: str) -> tuple[str, Dict[str, Any]]:
    """归一化 + 形状校验 + 分发到对应源。返回 (归一化 id, meta)。
    meta 一定含 exists；不存在 / 形状错时 exists=false 且带 error。"""
    id_type = (id_type or "").lower()
    ident = _normalize_id(id_type, ident_raw or "")
    shape_err = _validate_shape(id_type, ident)
    if shape_err:
        return ident, {"exists": False, "error": shape_err}
    try:
        if id_type == "pmid":
            return ident, _verify_pmid(ident)
        if id_type == "doi":
            return ident, _verify_doi(ident)
        if id_type == "nct":
            return ident, _verify_nct(ident)
        return ident, {"exists": False, "error": f"unknown id_type: {id_type}"}
    except Exception as e:  # noqa: BLE001
        return ident, {"exists": False, "error": str(e)}


# ---------- 元数据 vs claim 的启发式警告 ----------

_HUMAN_HINTS = ("patient", "adult", "child", "human", "cohort", "population", "in vivo human")
_ANIMAL_HINTS = ("mouse", "mice", "rat", "murine", "zebrafish", "porcine", "canine",
                 "primate", "monkey", "rabbit")
_INVITRO_HINTS = ("cell line", "in vitro", "cultured", "hek293", "hela", "spheroid", "organoid")


def _spot_species_gap(claim_text: str, ref_meta: Dict[str, Any]) -> Optional[str]:
    """若 claim 谈的是"人"，而参考文献看起来是动物/体外，标红一个 warning。"""
    if not ref_meta.get("exists"):
        return None
    text = " ".join(str(ref_meta.get(k) or "") for k in ("title", "abstract", "official_title"))
    text_low = text.lower()
    claim_low = (claim_text or "").lower()
    claim_is_human = any(h in claim_low for h in _HUMAN_HINTS) or any(
        w in claim_low for w in ("患者", "病人", "人群", "临床")
    )
    ref_is_animal = any(h in text_low for h in _ANIMAL_HINTS)
    ref_is_invitro = any(h in text_low for h in _INVITRO_HINTS)
    if claim_is_human and ref_is_animal and not any(h in text_low for h in _HUMAN_HINTS):
        return "claim 涉及人类结论，但参考文献看起来是动物实验（title/abstract 含动物模型关键词）"
    if claim_is_human and ref_is_invitro and not any(h in text_low for h in _HUMAN_HINTS):
        return "claim 涉及人类结论，但参考文献看起来是体外/细胞实验"
    return None


# ---------- MCP 工具 ----------

@server.tool(
    "evidence_verify",
    "Verify a batch of medical claims against their citations (PMID / DOI / NCT). "
    "Returns per-reference existence, canonical metadata, evidence type, and species-mismatch warnings. "
    "Non-existent IDs are flagged; do NOT ask this tool to 'find similar' — hallucinated citations are the target of this audit.",
    {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The claim sentence"},
                        "refs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id_type": {"type": "string", "enum": ["pmid", "doi", "nct"]},
                                    "id": {"type": "string"},
                                },
                                "required": ["id_type", "id"],
                            },
                        },
                    },
                    "required": ["text", "refs"],
                },
            },
        },
        "required": ["claims"],
    },
)
def evidence_verify(claims: List[Dict[str, Any]]):
    audited: List[Dict[str, Any]] = []
    for c in claims:
        text = c.get("text", "")
        refs = c.get("refs", []) or []
        out_refs = []
        for r in refs:
            id_type = (r.get("id_type") or "").lower()
            ident = _normalize_id(id_type, r.get("id", ""))
            shape_err = _validate_shape(id_type, ident)
            if shape_err:
                out_refs.append({"id_type": id_type, "id": ident,
                                 "exists": False, "error": shape_err})
                continue
            try:
                if id_type == "pmid":
                    meta = _verify_pmid(ident)
                elif id_type == "doi":
                    meta = _verify_doi(ident)
                elif id_type == "nct":
                    meta = _verify_nct(ident)
                else:
                    meta = {"exists": False, "error": f"unknown id_type: {id_type}"}
            except Exception as e:  # noqa: BLE001
                meta = {"exists": False, "error": str(e)}
            warning = _spot_species_gap(text, meta)
            entry = {"id_type": id_type, "id": ident, **meta}
            if warning:
                entry["warning"] = warning
            out_refs.append(entry)
        # 结论级审计标记
        has_any_valid = any(r.get("exists") for r in out_refs)
        has_hallucinated = any(not r.get("exists") for r in out_refs)
        audited.append({
            "claim": text,
            "refs": out_refs,
            "verdict": "unsupported" if not has_any_valid else (
                "partially_supported" if has_hallucinated else "supported"
            ),
            "warnings": [r["warning"] for r in out_refs if r.get("warning")],
        })
    total = len(audited)
    n_unsupported = sum(1 for a in audited if a["verdict"] == "unsupported")
    n_partial = sum(1 for a in audited if a["verdict"] == "partially_supported")
    return {
        "summary": {
            "total_claims": total,
            "unsupported": n_unsupported,
            "partially_supported": n_partial,
            "fully_supported": total - n_unsupported - n_partial,
        },
        "claims": audited,
    }


@server.tool(
    "evidence_classify",
    "Given a PMID, return normalized evidence type (meta-analysis / systematic-review / RCT / clinical-trial / cohort / case-control / observational / case-series / narrative-review / guideline / editorial / letter / comment / unclassified). "
    "Classification is derived strictly from MeSH publication_types on the record — not from title/abstract heuristics.",
    {
        "type": "object",
        "properties": {"pmid": {"type": "string"}},
        "required": ["pmid"],
    },
)
def evidence_classify(pmid: str):
    meta = _verify_pmid(_normalize_id("pmid", pmid))
    if not meta.get("exists"):
        return {"pmid": pmid, "exists": False}
    return {
        "pmid": pmid,
        "exists": True,
        "evidence_type": meta.get("evidence_type"),
        "publication_types": meta.get("publication_types"),
    }


@server.tool(
    "evidence_build_table",
    "Build a compact evidence table (Markdown) for a list of verified claims. "
    "Columns: 结论 · 来源 · 类型 · 年份 · n · 局限 · 冲突. "
    "Pass the same `claims` you validated with evidence_verify (or the tool's `claims` field back).",
    {
        "type": "object",
        "properties": {
            "audited_claims": {
                "type": "array",
                "description": "Output of evidence_verify.claims (each has claim, refs, verdict).",
                "items": {"type": "object"},
            },
            "language": {"type": "string", "enum": ["zh", "en"], "default": "zh"},
        },
        "required": ["audited_claims"],
    },
)
def evidence_build_table(audited_claims: List[Dict[str, Any]], language: str = "zh"):
    headers_zh = ["#", "结论", "来源", "证据类型", "年份", "n / 期别", "局限 / 警告", "结论评级"]
    headers_en = ["#", "Claim", "Source", "Evidence type", "Year", "n / phase", "Limitations", "Verdict"]
    headers = headers_zh if language == "zh" else headers_en
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    verdict_zh = {"supported": "支持", "partially_supported": "部分支持",
                  "unsupported": "无有效引用（可能为幻觉）"}
    for i, c in enumerate(audited_claims, 1):
        claim = (c.get("claim") or "").replace("|", "\\|").replace("\n", " ")
        # 逐 ref 挑一条最强证据展示
        best_ref = None
        strength_order = ["meta-analysis", "systematic-review", "RCT", "clinical-trial",
                          "cohort", "case-control", "observational",
                          "case-series", "narrative-review", "unclassified"]
        best_rank = 999
        for r in c.get("refs", []):
            if not r.get("exists"):
                continue
            et = r.get("evidence_type") or "unclassified"
            try:
                rank = strength_order.index(et)
            except ValueError:
                rank = 999
            if rank < best_rank:
                best_rank = rank
                best_ref = r
        if best_ref is None:
            row = [str(i), claim, "—", "—", "—", "—",
                   "; ".join(c.get("warnings") or []) or "所有引用未通过校验",
                   verdict_zh.get(c.get("verdict"), c.get("verdict"))]
        else:
            src_bits = []
            if best_ref.get("id_type") == "pmid":
                src_bits.append(f"PMID:{best_ref.get('id')}")
            elif best_ref.get("id_type") == "doi":
                src_bits.append(f"DOI:{best_ref.get('id')}")
            elif best_ref.get("id_type") == "nct":
                src_bits.append(f"NCT:{best_ref.get('id')}")
            if best_ref.get("journal"):
                src_bits.append(str(best_ref.get("journal"))[:40])
            n_phase = str(best_ref.get("enrollment") or "") or (best_ref.get("phase") or "")
            row = [
                str(i), claim, " · ".join(src_bits),
                best_ref.get("evidence_type") or "—",
                str(best_ref.get("year") or "—"),
                n_phase or "—",
                "; ".join(c.get("warnings") or []) or "—",
                verdict_zh.get(c.get("verdict"), c.get("verdict")),
            ]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# =====================================================================
# Claim-Level Evidence Graph（需求 1）
# =====================================================================
# 不止「PMID 存不存在」，而是把每条结论拆成 claim，绑定：证据 · 物种 · 人群 ·
# 样本量 · 实验类型 · 疾病阶段 · 干预 · 反证，并算出「适用边界」与「冲突」。


@server.tool(
    "evidence_profile",
    "Deep-profile a single citation (PMID / DOI / NCT): species, population (age/sex), "
    "sample size, experiment type (e.g. 临床 II 期 / 动物 / 体外 / 回顾性队列), disease stage. "
    "Every inference carries the signals it was derived from (MeSH terms / abstract snippets) — "
    "not a black box. Use before binding a citation to a human-clinical claim.",
    {
        "type": "object",
        "properties": {
            "id_type": {"type": "string", "enum": ["pmid", "doi", "nct"]},
            "id": {"type": "string"},
        },
        "required": ["id_type", "id"],
    },
)
def evidence_profile(id_type: str, id: str):  # noqa: A002
    ident, meta = _verify_ref(id_type, id)
    if not meta.get("exists"):
        return {"id_type": id_type.lower(), "id": ident, "exists": False,
                "error": meta.get("error")}
    profile = _ep.build_profile(meta)
    return {
        "id_type": id_type.lower(), "id": ident, "exists": True,
        "title": meta.get("title") or meta.get("official_title"),
        "journal": meta.get("journal"),
        "profile": profile,
    }


def _boundary_from_supporting(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从一条 claim 的所有支持证据合成「适用边界」。"""
    species = {p["species"]["value"] for p in profiles
              if p.get("species", {}).get("value") not in (None, "unknown")}
    ages, sexes, stages = set(), set(), set()
    ns: List[int] = []
    for p in profiles:
        ages.update(p.get("population", {}).get("age_groups") or [])
        sexes.update(p.get("population", {}).get("sex") or [])
        sv = p.get("disease_stage", {}).get("value")
        if sv:
            stages.add(sv)
        n = p.get("sample_size", {}).get("n")
        if n:
            ns.append(n)
    # 物种边界：全人类 / 仅临床前 / 混合
    if species == {"human"}:
        species_note = "人类证据"
    elif species and species <= {"animal", "in-vitro"}:
        species_note = "仅临床前证据（动物 / 体外）——推广到人类为外推"
    elif species:
        species_note = "人类 + 临床前混合证据"
    else:
        species_note = "物种不明"
    return {
        "species": sorted(species),
        "species_note": species_note,
        "age_groups": sorted(ages),
        "sex": sorted(sexes),
        "disease_stage": sorted(stages),
        "max_sample_size": max(ns) if ns else None,
        "n_supporting": len(profiles),
    }


def _grade_of(profiles: List[Dict[str, Any]]) -> str:
    """一条 claim 的最强证据等级标签（人可读）。"""
    order = ["meta-analysis", "systematic-review", "RCT", "clinical-trial", "guideline",
             "cohort", "case-control", "observational", "case-series",
             "narrative-review", "preprint", "unclassified"]
    best_rank, best_label = 999, "无有效证据"
    for p in profiles:
        et = p.get("experiment", {}).get("evidence_type") or "unclassified"
        try:
            rank = order.index(et)
        except ValueError:
            rank = 999
        if rank < best_rank:
            best_rank = rank
            best_label = p.get("experiment", {}).get("label") or et
    return best_label


@server.tool(
    "evidence_graph",
    "Build a claim-level evidence graph. For EACH claim: verify its citations, deep-profile "
    "each (species/population/n/experiment-type/disease-stage), then compute (a) evidence level, "
    "(b) applicability boundary (适用边界), (c) conflicts — including asserted-vs-actual mismatches "
    "(claim says 'human' but evidence is animal) and stance conflicts, (d) counter-evidence (反证). "
    "Returns machine-readable nodes/edges + a per-claim verdict. This is the audit backbone: "
    "the model decomposes claims + tags each ref's stance (supports/refutes); the tool binds evidence.",
    {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The claim sentence"},
                        "asserted": {
                            "type": "object",
                            "description": "What the claim implicitly asserts, for mismatch detection.",
                            "properties": {
                                "species": {"type": "string", "enum": ["human", "animal", "in-vitro", "mixed"]},
                                "population": {"type": "string"},
                                "intervention": {"type": "string"},
                                "endpoint": {"type": "string"},
                                "disease_stage": {"type": "string"},
                            },
                        },
                        "refs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id_type": {"type": "string", "enum": ["pmid", "doi", "nct"]},
                                    "id": {"type": "string"},
                                    "stance": {"type": "string", "enum": ["supports", "refutes"],
                                               "default": "supports"},
                                },
                                "required": ["id_type", "id"],
                            },
                        },
                    },
                    "required": ["text", "refs"],
                },
            },
        },
        "required": ["claims"],
    },
)
def evidence_graph(claims: List[Dict[str, Any]]):
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    claim_reports: List[Dict[str, Any]] = []
    ev_seen: Dict[str, str] = {}  # (id_type:id) -> node_id, 去重共享证据

    for ci, c in enumerate(claims):
        claim_id = f"claim:{ci}"
        text = c.get("text", "")
        asserted = c.get("asserted") or {}
        nodes.append({"id": claim_id, "type": "claim", "text": text, "asserted": asserted})

        supporting_profiles: List[Dict[str, Any]] = []
        counter_evidence: List[Dict[str, Any]] = []
        conflicts: List[str] = []
        ref_out: List[Dict[str, Any]] = []

        for r in c.get("refs", []) or []:
            id_type = (r.get("id_type") or "").lower()
            stance = (r.get("stance") or "supports").lower()
            ident, meta = _verify_ref(id_type, r.get("id", ""))
            key = f"{id_type}:{ident}"
            ev_node_id = ev_seen.get(key)
            profile = _ep.build_profile(meta) if meta.get("exists") else {"exists": False}
            if ev_node_id is None:
                ev_node_id = f"evidence:{len(ev_seen)}"
                ev_seen[key] = ev_node_id
                nodes.append({
                    "id": ev_node_id, "type": "evidence",
                    "id_type": id_type, "ref_id": ident,
                    "exists": bool(meta.get("exists")),
                    "title": meta.get("title") or meta.get("official_title"),
                    "profile": profile,
                    "error": meta.get("error"),
                })
            edges.append({"from": claim_id, "to": ev_node_id, "stance": stance,
                          "exists": bool(meta.get("exists"))})
            entry = {"id_type": id_type, "id": ident, "stance": stance,
                     "exists": bool(meta.get("exists"))}

            if not meta.get("exists"):
                conflicts.append(f"引用 {id_type.upper()}:{ident} 不存在（{meta.get('error') or '上游 404'}）"
                                 "——不可作为证据")
                ref_out.append(entry)
                continue

            if stance == "refutes":
                counter_evidence.append({"id_type": id_type, "id": ident,
                                         "label": profile.get("experiment", {}).get("label"),
                                         "title": meta.get("title") or meta.get("official_title")})
                ref_out.append(entry)
                continue

            supporting_profiles.append(profile)
            # 断言 vs 实际：物种错配
            asserted_sp = (asserted.get("species") or "").lower()
            actual_sp = profile.get("species", {}).get("value")
            if asserted_sp == "human" and actual_sp in ("animal", "in-vitro"):
                conflicts.append(
                    f"错配：claim 断言人类，但支持证据 {id_type.upper()}:{ident} "
                    f"实为 {actual_sp}（{'；'.join(profile['species']['signals'][:3])}）")
            ref_out.append(entry)

        exists_support = len(supporting_profiles)
        has_counter = len(counter_evidence) > 0
        if exists_support and has_counter:
            conflicts.append(f"存在反证：{len(counter_evidence)} 条引用与结论方向相反")

        if not exists_support:
            verdict = "unsupported"
        elif conflicts:
            verdict = "contested"
        else:
            verdict = "supported"

        boundary = _boundary_from_supporting(supporting_profiles) if supporting_profiles else None
        grade = _grade_of(supporting_profiles) if supporting_profiles else "无有效证据"

        claim_reports.append({
            "claim": text,
            "verdict": verdict,
            "evidence_level": grade,
            "applicability_boundary": boundary,
            "conflicts": conflicts,
            "counter_evidence": counter_evidence,
            "refs": ref_out,
        })

    summary = {
        "total_claims": len(claim_reports),
        "supported": sum(1 for r in claim_reports if r["verdict"] == "supported"),
        "contested": sum(1 for r in claim_reports if r["verdict"] == "contested"),
        "unsupported": sum(1 for r in claim_reports if r["verdict"] == "unsupported"),
        "claims_with_conflicts": sum(1 for r in claim_reports if r["conflicts"]),
    }
    return {"summary": summary, "claims": claim_reports,
            "graph": {"nodes": nodes, "edges": edges}}


# =====================================================================
# 不确定性台账 Uncertainty Ledger（需求 2）
# =====================================================================
# 每个工作流都必须暴露：Known knowns / Known unknowns / Conflicts / Missing data /
# Next experiment。这个工具从 evidence_graph 的输出自动派生大部分条目，再让模型补充。


def _derive_missing_data(claim: Dict[str, Any]) -> List[str]:
    """从一条 claim 的边界自动发现缺失数据。"""
    out: List[str] = []
    b = claim.get("applicability_boundary") or {}
    if claim.get("verdict") == "unsupported":
        return out  # 无支持证据的直接进 known_unknowns，不重复
    if b.get("species_note", "").startswith("仅临床前"):
        out.append(f"「{claim['claim'][:40]}」缺人体证据（当前仅动物 / 体外）")
    if not b.get("max_sample_size"):
        out.append(f"「{claim['claim'][:40]}」支持证据未报告样本量（无法判断统计效力）")
    if not b.get("disease_stage"):
        out.append(f"「{claim['claim'][:40]}」未界定疾病阶段 / 分层（适用人群不清）")
    return out


@server.tool(
    "uncertainty_ledger",
    "Compile the mandatory uncertainty panel every research workflow must expose: "
    "Known knowns / Known unknowns / Conflicts / Missing data / Next experiment. "
    "Auto-derives entries from an evidence_graph result (supported claims → known knowns; "
    "unsupported → known unknowns; graph conflicts/counter-evidence → conflicts; narrow "
    "boundaries → missing data) and merges the model's own additions. Renders Markdown.",
    {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The research question, if any"},
            "graph_claims": {
                "type": "array",
                "description": "The `claims` array from evidence_graph output.",
                "items": {"type": "object"},
            },
            "extra": {
                "type": "object",
                "description": "Model-supplied additions to each bucket (free text items).",
                "properties": {
                    "known_unknowns": {"type": "array", "items": {"type": "string"}},
                    "missing_data": {"type": "array", "items": {"type": "string"}},
                    "next_experiments": {"type": "array", "items": {"type": "string"}},
                    "conflicts": {"type": "array", "items": {"type": "string"}},
                },
            },
            "language": {"type": "string", "enum": ["zh", "en"], "default": "zh"},
        },
        "required": ["graph_claims"],
    },
)
def uncertainty_ledger(graph_claims: List[Dict[str, Any]],
                       question: str = "", extra: Optional[Dict[str, Any]] = None,
                       language: str = "zh"):
    extra = extra or {}
    known_knowns: List[str] = []
    known_unknowns: List[str] = []
    conflicts: List[str] = []
    missing_data: List[str] = []
    next_experiments: List[str] = []

    for c in graph_claims or []:
        claim_txt = c.get("claim", "")
        verdict = c.get("verdict")
        level = c.get("evidence_level")
        b = c.get("applicability_boundary") or {}
        if verdict == "supported":
            boundary_bits = []
            if b.get("species_note"):
                boundary_bits.append(b["species_note"])
            if b.get("disease_stage"):
                boundary_bits.append("阶段: " + ", ".join(b["disease_stage"]))
            if b.get("max_sample_size"):
                boundary_bits.append(f"n≤{b['max_sample_size']}")
            known_knowns.append(
                f"{claim_txt} —— 证据等级 {level}"
                + (f"；适用边界：{'；'.join(boundary_bits)}" if boundary_bits else ""))
        elif verdict == "unsupported":
            known_unknowns.append(f"{claim_txt} —— 无有效引用支持，尚不能确证")
        elif verdict == "contested":
            known_knowns.append(f"{claim_txt}（有争议，见 Conflicts）—— 证据等级 {level}")
        for conf in c.get("conflicts", []) or []:
            conflicts.append(conf)
        for ce in c.get("counter_evidence", []) or []:
            conflicts.append(f"反证：{ce.get('id_type','').upper()}:{ce.get('id')} "
                             f"（{ce.get('label') or '类型不明'}）与「{claim_txt[:30]}」相反")
        missing_data.extend(_derive_missing_data(c))
        # 自动建议下一步实验
        if verdict == "unsupported":
            next_experiments.append(f"为「{claim_txt[:40]}」补一条可核对的一手证据（PMID/NCT），否则撤回")
        elif b.get("species_note", "").startswith("仅临床前"):
            next_experiments.append(f"设计人体研究验证「{claim_txt[:40]}」（当前仅临床前）")

    # 合并模型补充
    known_unknowns += list(extra.get("known_unknowns") or [])
    missing_data += list(extra.get("missing_data") or [])
    next_experiments += list(extra.get("next_experiments") or [])
    conflicts += list(extra.get("conflicts") or [])

    def _dedup(xs: List[str]) -> List[str]:
        seen, out = set(), []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    ledger = {
        "known_knowns": _dedup(known_knowns),
        "known_unknowns": _dedup(known_unknowns),
        "conflicts": _dedup(conflicts),
        "missing_data": _dedup(missing_data),
        "next_experiment": _dedup(next_experiments),
    }

    # 渲染 Markdown
    titles_zh = {
        "known_knowns": "✅ Known knowns（已知已确证）",
        "known_unknowns": "❓ Known unknowns（已知的未知）",
        "conflicts": "⚔️ Conflicts（证据冲突 / 反证）",
        "missing_data": "🕳️ Missing data（缺失数据 / 盲区）",
        "next_experiment": "🔬 Next experiment（下一步实验建议）",
    }
    lines = ["## 不确定性面板（Uncertainty Panel）"]
    if question:
        lines.append(f"> 研究问题：{question}")
    for key in ("known_knowns", "known_unknowns", "conflicts", "missing_data", "next_experiment"):
        lines.append("")
        lines.append(f"### {titles_zh[key]}")
        items = ledger[key]
        if not items:
            lines.append("- （无 —— 若本应有内容而为空，说明检索/审计尚不充分）")
        else:
            for it in items:
                lines.append(f"- {it}")
    return {"ledger": ledger, "markdown": "\n".join(lines)}


if __name__ == "__main__":
    server.run()
