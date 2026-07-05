#!/usr/bin/env python3
"""临床试验 landscape 报告生成器。

给一个 (indication, intervention) 或 target 名，跑一遍 CT.gov，产出：
  1) 按 phase × status 的数量矩阵
  2) 主要 endpoint 频率表（哪些终点最常用）
  3) 主要 sponsor 排名
  4) 地理分布（前 10 国）
  5) 一个 markdown 报告骨架（可直接贴进 landscape 分析文档）

设计原则：
  - **一律用 v2 API 真实数据**，不允许模型编 NCT / 编数据
  - endpoint 频率表按原文归并（"Overall Survival" / "OS" 归为同一条）
  - sponsor 名规范化：括号内容剥除、连字符归一

CLI：
    python packs/bio-workflows/generators/ct_landscape.py \\
        --condition "non-small cell lung cancer" \\
        --intervention "pembrolizumab OR nivolumab" \\
        --out-md reports/nsclc-io-landscape.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _lib import http  # noqa: E402


_BASE = "https://clinicaltrials.gov/api/v2"


def _fetch_all(condition: str, intervention: Optional[str],
               sponsor: Optional[str], page_limit: int = 5) -> List[Dict[str, Any]]:
    """分页拉 —— page_limit 是**上限**页数（默认 5 × 100 = 500 条）。"""
    all_studies: List[Dict[str, Any]] = []
    token = None
    for _ in range(page_limit):
        p: Dict[str, Any] = {"format": "json", "pageSize": 100}
        if condition:
            p["query.cond"] = condition
        if intervention:
            p["query.intr"] = intervention
        if sponsor:
            p["query.spons"] = sponsor
        if token:
            p["pageToken"] = token
        data = http.get_json(f"{_BASE}/studies", params=p)
        studies = (data or {}).get("studies") or []
        all_studies.extend(studies)
        token = (data or {}).get("nextPageToken")
        if not token:
            break
    return all_studies


def _phase_key(phases: Optional[List[str]]) -> str:
    if not phases:
        return "NOT_APPLICABLE"
    # 只取第一个 phase（v2 可能返回多 phase 列表）
    return phases[0] or "NOT_APPLICABLE"


_PHASE_ORDER = ["EARLY_PHASE1", "PHASE1", "PHASE1_2", "PHASE2", "PHASE2_3",
                "PHASE3", "PHASE4", "NOT_APPLICABLE"]
_STATUS_ORDER = ["RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION",
                 "NOT_YET_RECRUITING", "COMPLETED", "TERMINATED", "SUSPENDED",
                 "WITHDRAWN", "UNKNOWN"]


_ENDPOINT_ALIASES = {
    # 简单归并
    r"^overall survival.*|^os$": "Overall Survival (OS)",
    r"^progression[- ]free survival.*|^pfs$": "Progression-Free Survival (PFS)",
    r"^objective response rate.*|^orr$": "Objective Response Rate (ORR)",
    r"^disease[- ]free survival.*|^dfs$": "Disease-Free Survival (DFS)",
    r"^event[- ]free survival.*|^efs$": "Event-Free Survival (EFS)",
    r"^duration of response.*|^dor$": "Duration of Response (DoR)",
    r"^complete response.*|^cr rate": "Complete Response Rate",
    r"^partial response.*|^pr rate": "Partial Response Rate",
    r"^time to progression.*|^ttp$": "Time to Progression (TTP)",
    r"^adverse events?.*": "Adverse Events (AE)",
    r"^dose[- ]limiting toxicit.*|^dlt": "Dose-Limiting Toxicity (DLT)",
    r"^maximum tolerated dose.*|^mtd": "Maximum Tolerated Dose (MTD)",
    r"^pharmacokinetic.*|^pk$": "Pharmacokinetics (PK)",
    r"^quality of life.*|^qol$": "Quality of Life (QoL)",
}


def _canonicalize_endpoint(name: str) -> str:
    lower = name.lower().strip()
    for pat, canonical in _ENDPOINT_ALIASES.items():
        if re.match(pat, lower):
            return canonical
    return name.strip()


def _canonicalize_sponsor(name: str) -> str:
    if not name:
        return "(unknown)"
    # 剥括号内容
    s = re.sub(r"\s*\([^)]*\)", "", name)
    # 归一 "Inc." / "LLC" / ", Ltd."
    s = re.sub(r"\s*,?\s*(Inc|LLC|Ltd|Co|Corp|SA|GmbH|AG)\.?\s*$", "", s, flags=re.I)
    return s.strip() or "(unknown)"


def build_landscape(studies: List[Dict[str, Any]]) -> Dict[str, Any]:
    matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    primary_endpoints = Counter()
    secondary_endpoints = Counter()
    sponsors = Counter()
    countries = Counter()
    trials_by_country: Dict[str, List[str]] = defaultdict(list)
    nct_ids: List[str] = []

    for s in studies:
        prot = s.get("protocolSection") or {}
        ident = prot.get("identificationModule") or {}
        status = prot.get("statusModule") or {}
        design = prot.get("designModule") or {}
        outcomes = prot.get("outcomesModule") or {}
        contacts = prot.get("contactsLocationsModule") or {}
        sponsor_mod = prot.get("sponsorCollaboratorsModule") or {}

        nct = ident.get("nctId")
        if nct:
            nct_ids.append(nct)
        st = status.get("overallStatus") or "UNKNOWN"
        ph = _phase_key(design.get("phases"))
        matrix[ph][st] += 1

        for o in outcomes.get("primaryOutcomes") or []:
            if m := o.get("measure"):
                primary_endpoints[_canonicalize_endpoint(m)] += 1
        for o in outcomes.get("secondaryOutcomes") or []:
            if m := o.get("measure"):
                secondary_endpoints[_canonicalize_endpoint(m)] += 1

        lead = (sponsor_mod.get("leadSponsor") or {}).get("name")
        if lead:
            sponsors[_canonicalize_sponsor(lead)] += 1

        for l in contacts.get("locations") or []:
            country = l.get("country")
            if country:
                countries[country] += 1
                if nct:
                    trials_by_country[country].append(nct)

    return {
        "n_trials": len(studies),
        "nct_ids": nct_ids,
        "phase_status_matrix": {ph: dict(m) for ph, m in matrix.items()},
        "primary_endpoints": primary_endpoints.most_common(30),
        "secondary_endpoints": secondary_endpoints.most_common(30),
        "top_sponsors": sponsors.most_common(20),
        "top_countries": countries.most_common(20),
    }


def to_markdown(landscape: Dict[str, Any], condition: str,
                intervention: Optional[str], sponsor: Optional[str]) -> str:
    parts = []
    filters = [f"condition = *{condition}*"]
    if intervention:
        filters.append(f"intervention = *{intervention}*")
    if sponsor:
        filters.append(f"sponsor = *{sponsor}*")
    parts.append(f"# 临床试验 Landscape 报告\n")
    parts.append(f"**筛选条件**: {' · '.join(filters)}\n")
    parts.append(f"**试验总数**: {landscape['n_trials']}（v2 API 数据；仅包含 ClinicalTrials.gov 注册库）\n")

    parts.append("## 数量矩阵（Phase × Status）\n")
    matrix = landscape["phase_status_matrix"]
    header = ["Phase"] + _STATUS_ORDER
    parts.append("| " + " | ".join(header) + " |")
    parts.append("|" + "|".join(["---"] * len(header)) + "|")
    for ph in _PHASE_ORDER:
        row = [ph]
        for st in _STATUS_ORDER:
            row.append(str(matrix.get(ph, {}).get(st, 0)))
        # 只在这一 phase 有数据时印
        if sum(int(x) for x in row[1:]) == 0:
            continue
        parts.append("| " + " | ".join(row) + " |")

    parts.append("\n## 主要终点 (Primary Endpoints)\n")
    parts.append("| 终点 | 试验数 |\n|---|---|")
    for ep, n in landscape["primary_endpoints"][:15]:
        parts.append(f"| {ep} | {n} |")

    parts.append("\n## Sponsor 前 10\n")
    parts.append("| Sponsor | 试验数 |\n|---|---|")
    for sp, n in landscape["top_sponsors"][:10]:
        parts.append(f"| {sp} | {n} |")

    parts.append("\n## 地理分布 前 10\n")
    parts.append("| 国家 | 试验数 |\n|---|---|")
    for c, n in landscape["top_countries"][:10]:
        parts.append(f"| {c} | {n} |")

    parts.append("\n## 附录：NCT 号清单\n")
    parts.append("<details><summary>点击展开</summary>\n\n")
    for i, nct in enumerate(landscape["nct_ids"]):
        parts.append(f"- {nct}" + ("\n" if i % 5 == 4 else ""))
    parts.append("\n</details>\n")

    parts.append(
        "\n---\n\n**数据说明**：仅覆盖 ClinicalTrials.gov（美国 NIH 注册库），"
        "不含 EudraCT / CHiCTR / ANZCTR / JAPIC。sponsor 名做过后缀归一（Inc / LLC 等），"
        "endpoint 名做过部分别名合并（OS / PFS / ORR / DFS 等）。\n"
    )
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", required=True)
    ap.add_argument("--intervention")
    ap.add_argument("--sponsor")
    ap.add_argument("--page-limit", type=int, default=5)
    ap.add_argument("--out-md", type=Path, help="写 markdown 报告到此路径")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    args = ap.parse_args()

    print(f"[ct_landscape] 拉取试验中（最多 {args.page_limit * 100} 条）…", file=sys.stderr)
    studies = _fetch_all(args.condition, args.intervention, args.sponsor, args.page_limit)
    print(f"[ct_landscape] 共 {len(studies)} 个试验，开始聚合…", file=sys.stderr)
    l = build_landscape(studies)

    if args.format == "json":
        print(json.dumps(l, ensure_ascii=False, indent=2, default=str))
        return 0

    md = to_markdown(l, args.condition, args.intervention, args.sponsor)
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md, "utf-8")
        print(f"[ct_landscape] Markdown → {args.out_md}", file=sys.stderr)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
