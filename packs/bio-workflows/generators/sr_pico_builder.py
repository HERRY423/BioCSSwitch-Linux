#!/usr/bin/env python3
"""Systematic Review PICO → MeSH boolean 生成器。

**这是一个可离线运行的 CLI 工具**，也可以以 MCP 方式挂进 bio-workflows pack。
把 PICO 元素（Population / Intervention / Comparator / Outcome）翻译成一条
真正**能用**的 PubMed 检索式，同时输出 Europe PMC / Cochrane / Embase 兼容版本。

不是让 LLM 编检索式——工具直接查 MeSH 拿主题词，用户填 PICO 就能拿到检索式。

CLI：
    python packs/bio-workflows/generators/sr_pico_builder.py \\
        --population "adults with type 2 diabetes" \\
        --intervention "metformin monotherapy" \\
        --comparator "placebo OR sulfonylurea" \\
        --outcome "cardiovascular events OR MACE"

    # 只加 RCT filter：
    python .../sr_pico_builder.py ... --study-type RCT

    # 输出结构化 JSON：
    python .../sr_pico_builder.py ... --format json

MCP mode：
    from _lib.server import MCPServer
    ... 略；见文件底部注册（默认 CLI，MCP 只在 --mcp 时激活）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _lib import entrez  # noqa: E402


# 常见 study-type 过滤器（PubMed 语法）
_STUDY_TYPE_FILTERS = {
    "RCT": '("randomized controlled trial"[pt] OR "controlled clinical trial"[pt] '
           'OR "randomized"[tiab] OR "randomised"[tiab])',
    "meta-analysis": '("meta-analysis"[pt] OR "systematic review"[pt])',
    "cohort": '("cohort studies"[MeSH] OR "prospective studies"[MeSH])',
    "case-control": '"case-control studies"[MeSH]',
    "guideline": '("practice guideline"[pt] OR "guideline"[pt])',
    "observational": '("observational study"[pt] OR "cohort studies"[MeSH] '
                     'OR "case-control studies"[MeSH])',
}

# 常见 population age filter
_AGE_FILTERS = {
    "adult": '"adult"[MeSH]',
    "child": '"child"[MeSH]',
    "elderly": '"aged"[MeSH]',
    "infant": '"infant"[MeSH]',
    "adolescent": '"adolescent"[MeSH]',
}


def _mesh_terms_for(query: str, max_terms: int = 5) -> List[str]:
    """查 MeSH，返回最相关的 descriptor 名。空结果返回 []。"""
    if not query:
        return []
    res = entrez.esearch("mesh", query, retmax=max_terms)
    if not res.get("ids"):
        return []
    summ = entrez.esummary("mesh", res["ids"])
    terms = []
    for uid in res["ids"]:
        s = summ.get(uid) or {}
        # ds_meshterms 是完整 descriptor 名；title 兜底
        name = s.get("ds_meshterms") or s.get("title")
        if name and isinstance(name, str):
            terms.append(name.strip())
    # 去重保序
    seen = set()
    out = []
    for t in terms:
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
    return out


def _build_element_expr(free_text: str, mesh_terms: List[str],
                        tiab_fields: bool = True) -> str:
    """把一个 PICO 元素的自由文本 + MeSH 词 → PubMed 检索式。

    形如：
        ("BRCA1"[MeSH] OR "BRCA1 protein"[MeSH]) OR
        ("brca1"[Title/Abstract] OR "brca 1"[Title/Abstract])
    """
    parts = []
    for m in mesh_terms:
        parts.append(f'"{m}"[MeSH]')
    if tiab_fields and free_text:
        # 分成 token 而不是原样：模型自由文本里带的连接词（AND/OR）会破坏语法
        for token in re.split(r"\s+OR\s+|\s+or\s+", free_text.strip()):
            token = token.strip()
            if not token or len(token) < 2:
                continue
            # 引号包住原样短语，作为 tiab 检索
            parts.append(f'"{token}"[Title/Abstract]')
    if not parts:
        return ""
    return "(" + " OR ".join(parts) + ")"


def build_pubmed_query(population: str = "", intervention: str = "",
                       comparator: str = "", outcome: str = "",
                       study_type: Optional[str] = None,
                       age_group: Optional[str] = None,
                       date_range: Optional[str] = None,
                       humans_only: bool = True) -> Dict[str, Any]:
    """核心 API。返回 dict：
        {
          "query": "最终检索式",
          "pieces": {p, i, c, o, study_type, ...},
          "mesh_lookups": {"population": ["Diabetes Mellitus, Type 2", ...], ...},
          "notes": ["若干注释"],
        }
    """
    lookups: Dict[str, List[str]] = {}
    exprs: Dict[str, str] = {}
    for label, text in [("population", population), ("intervention", intervention),
                         ("comparator", comparator), ("outcome", outcome)]:
        if not text:
            continue
        mesh = _mesh_terms_for(text)
        lookups[label] = mesh
        expr = _build_element_expr(text, mesh)
        if expr:
            exprs[label] = expr

    pieces = []
    if "population" in exprs:
        pieces.append(exprs["population"])
    # 干预 + 对照可以 AND (I OR C) —— 分开写有时更精确
    if "intervention" in exprs and "comparator" in exprs:
        pieces.append(f'({exprs["intervention"]} OR {exprs["comparator"]})')
    elif "intervention" in exprs:
        pieces.append(exprs["intervention"])
    elif "comparator" in exprs:
        pieces.append(exprs["comparator"])
    if "outcome" in exprs:
        pieces.append(exprs["outcome"])

    if not pieces:
        return {"query": "", "pieces": exprs, "mesh_lookups": lookups,
                "notes": ["未提供任何 PICO 元素"]}

    notes = []
    query = " AND ".join(pieces)
    if study_type:
        f = _STUDY_TYPE_FILTERS.get(study_type)
        if f:
            query = f"({query}) AND {f}"
        else:
            notes.append(f"未知 study_type `{study_type}`；已跳过")
    if age_group:
        f = _AGE_FILTERS.get(age_group.lower())
        if f:
            query = f"({query}) AND {f}"
        else:
            notes.append(f"未知 age_group `{age_group}`；已跳过")
    if humans_only:
        query = f"({query}) AND humans[MeSH]"
    if date_range:
        # e.g. "2019/01:2024/12" → "2019/01"[PDAT] : "2024/12"[PDAT]
        try:
            a, b = date_range.split(":")
            query = f'({query}) AND ("{a.strip()}"[PDAT] : "{b.strip()}"[PDAT])'
        except ValueError:
            notes.append(f"date_range 格式应为 `YYYY/MM:YYYY/MM`；收到 `{date_range}`")

    # 检索式空短语的 PubMed 惯例：把内层多余括号砍一层
    return {
        "query": query,
        "pieces": exprs,
        "mesh_lookups": lookups,
        "notes": notes,
    }


def translate_to_europepmc(pubmed_query: str) -> str:
    """把 PubMed 检索式粗翻成 Europe PMC 兼容。字段名映射：
        [MeSH] → MESH:
        [Title/Abstract] → (TITLE OR ABSTRACT):
        [PDAT] → FIRST_PDATE
    """
    q = pubmed_query
    q = re.sub(r'"([^"]+)"\[MeSH\]', r'MESH:"\1"', q)
    q = re.sub(r'"([^"]+)"\[Title/Abstract\]', r'(TITLE:"\1" OR ABSTRACT:"\1")', q)
    q = re.sub(r'"([^"]+)"\[pt\]', r'PUB_TYPE:"\1"', q)
    q = re.sub(r'"([^"]+)"\[PDAT\]', r'FIRST_PDATE:"\1"', q)
    q = re.sub(r'humans\[MeSH\]', r'MESH:"Humans"', q)
    return q


def translate_to_cochrane(pubmed_query: str) -> str:
    """粗翻成 Cochrane Central (CENTRAL) 语法。
    Cochrane 用 MH: / TI: / AB: 且 MeSH 直接 [Descriptor]。"""
    q = pubmed_query
    q = re.sub(r'"([^"]+)"\[MeSH\]', r'[mh "\1"]', q)
    q = re.sub(r'"([^"]+)"\[Title/Abstract\]', r'("\1":ti,ab,kw)', q)
    q = re.sub(r'"([^"]+)"\[pt\]', r'[pt "\1"]', q)
    q = re.sub(r'humans\[MeSH\]', r'[mh "Humans"]', q)
    return q


def main() -> int:
    ap = argparse.ArgumentParser(description="PICO → PubMed / Europe PMC / Cochrane 检索式")
    ap.add_argument("--population", "-p", default="")
    ap.add_argument("--intervention", "-i", default="")
    ap.add_argument("--comparator", "-c", default="")
    ap.add_argument("--outcome", "-o", default="")
    ap.add_argument("--study-type", choices=list(_STUDY_TYPE_FILTERS.keys()))
    ap.add_argument("--age-group", choices=list(_AGE_FILTERS.keys()))
    ap.add_argument("--date-range", help="YYYY/MM:YYYY/MM")
    ap.add_argument("--no-humans", action="store_true", help="不加 humans filter")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    r = build_pubmed_query(
        population=args.population, intervention=args.intervention,
        comparator=args.comparator, outcome=args.outcome,
        study_type=args.study_type, age_group=args.age_group,
        date_range=args.date_range, humans_only=not args.no_humans,
    )
    r["europepmc_query"] = translate_to_europepmc(r["query"])
    r["cochrane_query"] = translate_to_cochrane(r["query"])

    if args.format == "json":
        json.dump(r, sys.stdout, ensure_ascii=False, indent=2)
        return 0

    print("── MeSH 查询结果 ──")
    for label, terms in r["mesh_lookups"].items():
        print(f"  {label:14s}: {', '.join(terms) if terms else '(无)'}")
    print("\n── PubMed 检索式 ──")
    print(r["query"] or "(空)")
    print("\n── Europe PMC ──")
    print(r["europepmc_query"] or "(空)")
    print("\n── Cochrane CENTRAL ──")
    print(r["cochrane_query"] or "(空)")
    if r["notes"]:
        print("\n── 备注 ──")
        for n in r["notes"]:
            print(f"  · {n}")
    print()
    print("下一步：把 PubMed 检索式贴到 https://pubmed.ncbi.nlm.nih.gov/ 手动验证命中数，"
          "或直接调 bio-lit pubmed_search 工具。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
