#!/usr/bin/env python3
"""缩写 / 歧义术语消歧 MCP server —— bio-norm 的招牌工具。

工具：
  disambiguate  — 输入一个可能有歧义的术语（如 'APC'），加上可选上下文，
                  同时打 HGNC / MeSH / MONDO / HPO / GO / ChEBI，返回带评分的候选清单。
  disambiguate_multiple — 一次消歧多个术语，供上下文预处理批量走。

评分说明（简单可解释，避免把小模型的『黑箱评分』塞进去）：
  base_score = 1.0        源命中就 1.0
  + 0.5 若候选的 label / synonym 与查询字符串完全相等
  + 0.4 * context_overlap  （候选 description/synonym 与用户上下文的 token 集合 Jaccard）
  + 0.3 若命中的是"我们优先的本体"（disease→MONDO 优先于 DOID 等）
  上限 = 2.0；不做归一化——LLM 拿到分数就能判优先级，不需要百分比。
"""

from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import entrez, http  # noqa: E402
from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-norm-disambig", "0.1.0")

_HGNC = "https://rest.genenames.org"
_OLS = "https://www.ebi.ac.uk/ols4/api"
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "have", "has",
    "was", "are", "which", "when", "what", "who", "why", "how", "not", "but",
    "of", "in", "on", "to", "a", "an", "is", "at", "by", "as", "be", "or",
    "we", "our", "you", "your", "their", "his", "her", "its",
    "study", "studies", "paper", "papers", "research", "result", "results",
}


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {t.lower() for t in _TOKEN_RE.findall(text)
            if t.lower() not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _hgnc_candidates(term: str) -> List[Dict[str, Any]]:
    """HGNC 只按 gene symbol 打；命中就当"很可能是 gene"证据。"""
    out: List[Dict[str, Any]] = []
    # 1) 精确 fetch by current symbol
    try:
        data = http.get_json(f"{_HGNC}/fetch/symbol/{term}",
                             headers={"Accept": "application/json"})
        docs = ((data or {}).get("response") or {}).get("docs") or []
        for d in docs[:3]:
            out.append({
                "kind": "gene",
                "source": "HGNC",
                "canonical_id": d.get("hgnc_id"),
                "label": d.get("symbol"),
                "description": d.get("name"),
                "synonyms": (d.get("alias_symbol") or []) + (d.get("prev_symbol") or []),
                "exact_symbol_match": True,
                "xrefs": {"entrez": d.get("entrez_id"),
                          "ensembl": d.get("ensembl_gene_id"),
                          "uniprot": d.get("uniprot_ids") or []},
            })
    except Exception:
        pass
    # 2) fuzzy search（覆盖 previous symbol / alias / 拼错）
    try:
        data = http.get_json(f"{_HGNC}/search/{term}",
                             headers={"Accept": "application/json"})
        docs = ((data or {}).get("response") or {}).get("docs") or []
        # 已经在 exact 里的跳过
        seen = {c["canonical_id"] for c in out}
        for d in docs[:5]:
            hid = d.get("hgnc_id")
            if hid in seen:
                continue
            out.append({
                "kind": "gene",
                "source": "HGNC",
                "canonical_id": hid,
                "label": d.get("symbol"),
                "description": None,
                "synonyms": [],
                "exact_symbol_match": False,
                "search_score": d.get("score"),
            })
    except Exception:
        pass
    return out


def _mesh_candidates(term: str) -> List[Dict[str, Any]]:
    """MeSH 覆盖医学概念（细胞类型 / 病理生理 / 药理学等），常常是 gene 名撞车的另一头。"""
    out: List[Dict[str, Any]] = []
    try:
        res = entrez.esearch("mesh", term, retmax=5)
        ids = res["ids"]
        if not ids:
            return out
        summ = entrez.esummary("mesh", ids)
        for uid in ids:
            s = summ.get(uid) or {}
            label = s.get("ds_meshui") or s.get("title") or ""
            entry_terms = s.get("ds_entryterms") or []
            out.append({
                "kind": "mesh_concept",
                "source": "MeSH",
                "canonical_id": f"MESH:{uid}",
                "label": label,
                "description": s.get("ds_scopenote"),
                "synonyms": entry_terms,
                "tree_numbers": s.get("ds_meshtreenumberlist") or [],
            })
    except Exception:
        pass
    return out


_OLS_SCAN = [
    # ontology, kind, priority_boost（同类多本体命中时的优先级）
    ("mondo", "disease", 0.3),
    ("hp",    "phenotype", 0.3),
    ("go",    "pathway_or_function", 0.3),
    ("chebi", "chemical", 0.3),
    ("doid",  "disease", 0.0),  # DOID 与 MONDO 重叠时优先 MONDO
]


def _ols_candidates(term: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # 一次搜全部，再按 ontology 分桶（比每本体一次少 4 个 request）
    try:
        data = http.get_json(f"{_OLS}/search", params={"q": term, "rows": 30})
        docs = ((data or {}).get("response") or {}).get("docs") or []
    except Exception:
        return out
    kind_map = {o: (k, boost) for o, k, boost in _OLS_SCAN}
    for d in docs:
        onto = d.get("ontology_name")
        if onto not in kind_map:
            continue
        kind, boost = kind_map[onto]
        out.append({
            "kind": kind,
            "source": onto.upper(),
            "canonical_id": d.get("obo_id"),
            "label": d.get("label"),
            "description": (d.get("description") or [None])[0] if d.get("description") else None,
            "synonyms": d.get("synonym") or [],
            "_ols_priority_boost": boost,
            "iri": d.get("iri"),
        })
    return out


def _score(cand: Dict[str, Any], term: str, ctx_tokens: set[str]) -> float:
    score = 1.0
    label = (cand.get("label") or "").strip()
    if label.lower() == term.lower():
        score += 0.5
    for syn in cand.get("synonyms") or []:
        if syn and syn.strip().lower() == term.lower():
            score += 0.2
            break
    if cand.get("exact_symbol_match"):
        score += 0.5  # HGNC 精确 symbol 匹配的强证据
    if ctx_tokens:
        cand_text = " ".join([
            cand.get("label") or "",
            cand.get("description") or "",
            " ".join(cand.get("synonyms") or []),
        ])
        overlap = _jaccard(ctx_tokens, _tokens(cand_text))
        score += 0.4 * overlap
    score += cand.pop("_ols_priority_boost", 0.0)
    # 搜索分很低的 HGNC fuzzy 命中降权
    sscore = cand.get("search_score")
    if sscore is not None and sscore < 0.5:
        score -= 0.2
    return round(score, 3)


@server.tool(
    "disambiguate",
    "Given an ambiguous biomedical term (e.g. 'APC' = APC gene / Antigen-Presenting Cells / Anaphase-Promoting Complex / activated protein C), "
    "cross-check HGNC + MeSH + MONDO + HPO + GO + ChEBI in parallel and return **ranked** candidates with source IDs, descriptions, and a plain score. "
    "Pass `context` (a few sentences around where the term appeared) to boost candidates whose descriptions overlap the context.",
    {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "context": {"type": "string", "description": "Optional surrounding text to disambiguate. E.g. for 'APC' pass the whole paragraph."},
            "top_k": {"type": "integer", "default": 8, "minimum": 1, "maximum": 30},
        },
        "required": ["term"],
    },
)
def disambiguate(term: str, context: str = "", top_k: int = 8):
    term = (term or "").strip()
    if not term:
        return {"term": term, "candidates": []}
    ctx_tokens = _tokens(context) - _tokens(term)
    # 并行三路查（HGNC / MeSH / OLS），大量 IO 时间被合并
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_hgnc = ex.submit(_hgnc_candidates, term)
        f_mesh = ex.submit(_mesh_candidates, term)
        f_ols = ex.submit(_ols_candidates, term)
        all_cands = f_hgnc.result() + f_mesh.result() + f_ols.result()
    for c in all_cands:
        c["score"] = _score(c, term, ctx_tokens)
    # 去重（同一 canonical_id 保留最高分）
    dedup: Dict[str, Dict[str, Any]] = {}
    for c in all_cands:
        cid = c.get("canonical_id") or f"{c.get('source')}::{c.get('label')}"
        if cid not in dedup or c["score"] > dedup[cid]["score"]:
            dedup[cid] = c
    ranked = sorted(dedup.values(), key=lambda x: x["score"], reverse=True)
    return {
        "term": term,
        "context_tokens_used": sorted(ctx_tokens)[:20],
        "candidates": ranked[:top_k],
        "note": "分数是可解释的启发式：无 context 时相同分只按源顺序排；有 context 建议信 top-1，但当 top-1 与 top-2 分差 < 0.3 时提示用户/上游 LLM 显式确认。",
    }


@server.tool(
    "disambiguate_multiple",
    "Batch-disambiguate several terms sharing the same context. Same scoring as `disambiguate`.",
    {
        "type": "object",
        "properties": {
            "terms": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
            "context": {"type": "string"},
            "top_k_each": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
        },
        "required": ["terms"],
    },
)
def disambiguate_multiple(terms: List[str], context: str = "", top_k_each: int = 5):
    seen: Dict[str, Dict[str, Any]] = {}
    for t in terms:
        t = (t or "").strip()
        if not t or t in seen:
            continue
        seen[t] = disambiguate(term=t, context=context, top_k=top_k_each)
    return {"results": seen}


if __name__ == "__main__":
    server.run()
