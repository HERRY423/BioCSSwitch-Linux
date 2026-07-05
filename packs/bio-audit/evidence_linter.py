#!/usr/bin/env python3
"""证据 linter：批量检查 markdown / 文本文件里所有 PMID / DOI / NCT 是否真实存在。

**这是离线工具，不是 MCP**。使用场景：
  - 论文投稿前把 draft.md 扫一遍，防止挂到假 PMID / DOI
  - grant 标书交前审计 aims 页
  - reviewer response 交前检查每条 rebuttal 引用

CLI：
    python packs/bio-audit/evidence_linter.py draft.md
    python packs/bio-audit/evidence_linter.py --format json draft.md > report.json
    python packs/bio-audit/evidence_linter.py --strict rebuttal.md  # 有任何 fail 就返回非零

输出：
    ✓ PMID 12345678  — Metformin effect on cardiovascular events... (BMJ, 2018) [meta-analysis]
    ✗ PMID 99999999  — 不存在
    ⚠ DOI 10.x/y     — 存在但引用行说是 RCT，元数据显示是 case report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import entrez, http  # noqa: E402
from _lib.cache import memoize  # noqa: E402


_CROSSREF = "https://api.crossref.org/works"
_CTGOV = "https://clinicaltrials.gov/api/v2/studies"

_PMID_PAT = re.compile(r"\bPMID[:\s]*(\d{4,9})\b")
_DOI_PAT = re.compile(r"\bDOI[:\s]*(10\.\d{4,9}/\S+?)(?=[\s\]\)\.,;]|$)", re.IGNORECASE)
_NCT_PAT = re.compile(r"\b(NCT\d{8})\b")

# 弱信号：结论里出现这些词，我们期望引用是同级证据；不匹配就 warn。
_EVIDENCE_HINT_PATS = {
    "RCT": re.compile(r"\brandomized controlled trial\b|\brandomised controlled trial\b|\bRCT\b", re.I),
    "meta-analysis": re.compile(r"\bmeta[-\s]?analysis\b|\bsystematic review\b", re.I),
    "cohort": re.compile(r"\bcohort study\b|\bprospective cohort\b", re.I),
    "case-control": re.compile(r"\bcase[-\s]?control\b", re.I),
}


@dataclass
class Finding:
    id_type: str          # pmid / doi / nct
    id: str
    line_no: int
    line_text: str        # 该行原文；**默认不导出**（可能是病历 / 内部材料）。只在内存里用来做证据类型匹配。
    exists: bool
    metadata: Optional[Dict[str, Any]] = None
    warnings: Optional[List[str]] = None
    error: Optional[str] = None

    def line_sha256(self) -> str:
        """行内容的 sha256（前 16 hex）。用于关联同一行的多条 finding，而不泄露行原文。"""
        return hashlib.sha256((self.line_text or "").encode("utf-8")).hexdigest()[:16]


@memoize("linter_pmid", ttl_seconds=7 * 24 * 3600)
def _verify_pmid(pmid: str) -> Dict[str, Any]:
    xml = entrez.efetch_text("pubmed", [pmid], rettype="abstract", retmode="xml")
    parsed = entrez.parse_pubmed_xml(xml)
    if not parsed:
        return {"exists": False}
    return {"exists": True, **parsed[0]}


@memoize("linter_doi", ttl_seconds=30 * 24 * 3600)
def _verify_doi(doi: str) -> Dict[str, Any]:
    try:
        data = http.get_json(f"{_CROSSREF}/{doi}", params={"mailto": "csswitch-linter@localhost"})
    except Exception as e:  # noqa: BLE001
        return {"exists": False, "error": str(e)}
    msg = (data or {}).get("message") or {}
    if not msg:
        return {"exists": False}
    return {
        "exists": True,
        "title": (msg.get("title") or [""])[0],
        "journal": (msg.get("container-title") or [""])[0],
        "type": msg.get("type"),
    }


@memoize("linter_nct", ttl_seconds=7 * 24 * 3600)
def _verify_nct(nct: str) -> Dict[str, Any]:
    try:
        data = http.get_json(f"{_CTGOV}/{nct}", params={"format": "json"})
    except Exception as e:  # noqa: BLE001
        return {"exists": False, "error": str(e)}
    prot = (data or {}).get("protocolSection") or {}
    if not prot:
        return {"exists": False}
    ident = prot.get("identificationModule") or {}
    design = prot.get("designModule") or {}
    return {
        "exists": True,
        "title": ident.get("briefTitle"),
        "study_type": design.get("studyType"),
        "phase": (design.get("phases") or [None])[0],
    }


def _pubmed_evidence_type(meta: Dict[str, Any]) -> str:
    return meta.get("evidence_type") or "unclassified"


def _scan_line(line: str, line_no: int) -> List[Finding]:
    """在一行里抽所有 PMID / DOI / NCT，每个 → Finding（先只填 id + 位置，后面 verify）。"""
    out: List[Finding] = []
    for m in _PMID_PAT.finditer(line):
        out.append(Finding("pmid", m.group(1), line_no, line.rstrip(), exists=False))
    for m in _DOI_PAT.finditer(line):
        out.append(Finding("doi", m.group(1).rstrip(".;,)]"), line_no, line.rstrip(), exists=False))
    for m in _NCT_PAT.finditer(line):
        out.append(Finding("nct", m.group(1).upper(), line_no, line.rstrip(), exists=False))
    return out


def _check_evidence_type_match(line: str, ev_type: str) -> List[str]:
    warnings = []
    for expected, pat in _EVIDENCE_HINT_PATS.items():
        if not pat.search(line):
            continue
        # 引用行里出现了"RCT"字样 → 期望 ev_type 是 RCT 或更强
        stronger = {"meta-analysis", "systematic-review"}
        if expected == "RCT":
            if ev_type not in {"RCT", "clinical-trial"} and ev_type not in stronger:
                warnings.append(f"引用行提到 RCT，但元数据的 evidence_type 是 `{ev_type}`")
        elif expected == "meta-analysis":
            if ev_type not in stronger:
                warnings.append(f"引用行提到 meta-analysis / SR，但元数据的 evidence_type 是 `{ev_type}`")
        elif expected == "cohort":
            if ev_type not in {"cohort", "observational"} and ev_type not in stronger:
                warnings.append(f"引用行提到 cohort，但元数据的 evidence_type 是 `{ev_type}`")
    return warnings


def lint_file(path: Path) -> List[Finding]:
    findings: List[Finding] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            findings.extend(_scan_line(line, line_no))
    # verify each
    for f_ in findings:
        try:
            if f_.id_type == "pmid":
                meta = _verify_pmid(f_.id)
            elif f_.id_type == "doi":
                meta = _verify_doi(f_.id)
            elif f_.id_type == "nct":
                meta = _verify_nct(f_.id)
            else:
                meta = {"exists": False, "error": f"unknown type {f_.id_type}"}
        except Exception as e:  # noqa: BLE001
            meta = {"exists": False, "error": str(e)}
        f_.exists = bool(meta.get("exists"))
        f_.metadata = meta
        f_.error = meta.get("error")
        if f_.exists and f_.id_type == "pmid":
            ev = _pubmed_evidence_type(meta)
            f_.warnings = _check_evidence_type_match(f_.line_text, ev)
    return findings


def _fmt_finding_text(f: Finding) -> str:
    tag = "✓" if f.exists else "✗"
    if f.exists and f.warnings:
        tag = "⚠"
    id_str = f"{f.id_type.upper()} {f.id}"
    if not f.exists:
        return f"{tag} L{f.line_no:>4} {id_str:24s}  不存在" + (f"（{f.error}）" if f.error else "")
    m = f.metadata or {}
    title = str(m.get("title") or "")[:80]
    year = m.get("year") or "?"
    kind = m.get("evidence_type") or m.get("study_type") or m.get("type") or ""
    parts = [f"{tag} L{f.line_no:>4} {id_str:24s}  {title} ({year}) [{kind}]"]
    for w in f.warnings or []:
        parts.append(f"     ↳ {w}")
    return "\n".join(parts)


def main() -> int:
    # Windows 控制台默认 GBK，编不出 ✓/⚠ 等符号 → 强制 UTF-8 输出。
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="证据 linter（PMID / DOI / NCT 真实性校验）")
    ap.add_argument("files", nargs="+", type=Path, help="要扫描的 markdown / 文本文件")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--include-line-text", action="store_true",
                    help="JSON 里导出行原文（默认只给 line_sha256）。⚠ 行原文可能含 PHI / 内部材料，"
                         "扫病历 / 内部文档时不要开。")
    ap.add_argument("--no-metadata", action="store_true",
                    help="JSON 里不带公开文献元数据（有人把 abstract 也当敏感）。")
    ap.add_argument("--strict", action="store_true",
                    help="任何 fail（不存在或 warning）就返回非零；用于 CI")
    args = ap.parse_args()

    all_findings: Dict[str, List[Finding]] = {}
    for p in args.files:
        if not p.is_file():
            print(f"[linter] 跳过：{p} 不存在", file=sys.stderr)
            continue
        all_findings[str(p)] = lint_file(p)

    if args.format == "json":
        def _finding_json(f: Finding) -> Dict[str, Any]:
            d = {
                "id_type": f.id_type, "id": f.id, "line_no": f.line_no,
                # 默认只给行 hash（可关联同行 finding，不泄露内容）。
                "line_sha256": f.line_sha256(),
                "exists": f.exists,
                "warnings": f.warnings, "error": f.error,
            }
            # metadata 是公开文献元数据（PubMed/Crossref/CT.gov），非用户材料 → 默认带上。
            # 但 --no-metadata 可关（有人担心 abstract 也算敏感）。
            if not args.no_metadata:
                d["metadata"] = f.metadata
            # 行原文只在显式打开时导出（可能含 PHI / 内部材料）。
            if args.include_line_text:
                d["line_text"] = f.line_text
            return d

        json.dump({
            "_privacy": ("默认 JSON 只含 line_sha256，不含行原文；加 --include-line-text 才导出原文。"
                         if not args.include_line_text
                         else "⚠ 本报告含 --include-line-text：行原文已导出，可能含 PHI / 内部材料，勿外传。"),
            "files": {
                str(p): [_finding_json(f) for f in findings]
                for p, findings in all_findings.items()
            },
        }, sys.stdout, ensure_ascii=False, indent=2)
    else:
        for p, findings in all_findings.items():
            print(f"\n=== {p} ===")
            if not findings:
                print("  （未发现任何 PMID / DOI / NCT 引用）")
                continue
            n_ok = sum(1 for f in findings if f.exists and not f.warnings)
            n_warn = sum(1 for f in findings if f.exists and f.warnings)
            n_fail = sum(1 for f in findings if not f.exists)
            for f in findings:
                print(_fmt_finding_text(f))
            print(f"\n  合计：{len(findings)} 条 → ✓ {n_ok} · ⚠ {n_warn} · ✗ {n_fail}")

    # 退出码
    fails = 0
    for findings in all_findings.values():
        for f in findings:
            if not f.exists:
                fails += 1
            elif args.strict and f.warnings:
                fails += 1
    return 1 if (args.strict and fails) else 0


if __name__ == "__main__":
    sys.exit(main())
