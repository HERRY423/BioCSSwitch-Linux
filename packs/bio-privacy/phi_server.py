#!/usr/bin/env python3
"""PHI（Protected Health Information）检测与脱敏 MCP。

覆盖 HIPAA Safe Harbor 18 项里能靠正则和结构判断的部分：
  ✓ Names (启发式: 大写单词序列，配合上下文；准确率有限，标为 low_confidence)
  ✓ 日期 (YYYY-MM-DD / MM/DD/YYYY / DD.MM.YYYY / 中式 YYYY年MM月DD日)
  ✓ 电话（US +1-, CN 手机, 国际带 +）
  ✓ 邮箱
  ✓ SSN（US 9 位）/ 身份证号（CN 18 位）/ MRN（形态：letter+digit 混合）
  ✓ Web URL（可能含用户名）
  ✓ IP 地址
  ✓ 邮编（US 5/9 位，CN 6 位）
  ✓ 年龄 > 89（HIPAA 特别规定）
  ✗ 医院名 / 城市（无本地字典无法可靠识别；用户可通过 custom_patterns 补）

设计原则：
  1. **假阴性代价 > 假阳性代价**：宁可标错也不放过。所有匹配返回 confidence 让上游过滤。
  2. **不依赖任何模型**：全部正则；跑在用户机器上，不上传任何数据。
  3. **redact 是确定性替换**：同一份文档里同一个实体替换成同一个 token（[PATIENT_1] 保持一致），
     便于后续读者理解。
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-privacy-phi", "0.1.0")


# ---------- 正则 ----------
# 每条：kind, pattern, confidence, why_it_matches
_PATTERNS: List[Tuple[str, re.Pattern, str, str]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
     "high", "email address"),
    ("PHONE_INTL", re.compile(r"\+\d{1,3}[- ]?\d{1,4}[- ]?\d{3,4}[- ]?\d{3,4}"),
     "high", "international-format phone"),
    ("PHONE_US", re.compile(r"\b\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b"),
     "medium", "US-format 10-digit phone (may collide with other 10-digit strings)"),
    ("PHONE_CN_MOBILE", re.compile(r"\b1[3-9]\d{9}\b"),
     "high", "CN mobile phone (13x-19x + 9 digits)"),
    ("SSN_US", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
     "high", "US SSN pattern"),
    ("CN_ID", re.compile(r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"),
     "high", "CN national ID (18-digit with birthdate)"),
    ("DATE_ISO", re.compile(r"\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b"),
     "high", "ISO date"),
    ("DATE_US", re.compile(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(19|20)\d{2}\b"),
     "medium", "US-style date (M/D/Y)"),
    ("DATE_EU", re.compile(r"\b(0?[1-9]|[12]\d|3[01])\.(0?[1-9]|1[0-2])\.(19|20)\d{2}\b"),
     "medium", "European-style date (D.M.Y)"),
    ("DATE_CN", re.compile(r"(19|20)\d{2}年(0?[1-9]|1[0-2])月(0?[1-9]|[12]\d|3[01])日"),
     "high", "Chinese-style date"),
    ("URL", re.compile(r"https?://\S+"),
     "medium", "URL (may embed username / patient portal token)"),
    ("IP_V4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
     "low", "IPv4 (also many false positives on versioned strings)"),
    ("ZIP_US_9", re.compile(r"\b\d{5}-\d{4}\b"),
     "high", "US ZIP+4"),
    ("ZIP_US_5", re.compile(r"\b\d{5}\b(?!\d)"),
     "low", "5 digits (could be ZIP; many collisions)"),
    ("ZIP_CN_6", re.compile(r"\b\d{6}\b(?!\d)"),
     "low", "6 digits (could be CN ZIP; many collisions)"),
    # MRN 常见形态：字母前缀 + 6-10 位数字
    ("MRN_LIKE", re.compile(r"\b(?:MRN|mrn|病案号|住院号)[:：\s#]*[A-Z0-9]{5,12}\b"),
     "high", "explicitly labeled medical record number"),
    ("NHS_NUMBER", re.compile(r"\b\d{3}[- ]?\d{3}[- ]?\d{4}\b"),
     "medium", "UK NHS number pattern (10 digits)"),
]

# 高龄（>89 岁）
_AGE_HIGH = re.compile(r"\b(9\d|1[0-9]\d)\s*(?:岁|years?[- ]old|yo|yrs?)\b", re.I)

# Name candidates: 两个连续 Title-case 词或"张三先生"这类中文姓名 + 头衔
_NAME_LATIN = re.compile(r"\b(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Prof\.?)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b")
_NAME_LATIN_2 = re.compile(r"\b[A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,20}\b")   # 更弱：任意 Title Title
_NAME_CN = re.compile(r"([一-龥]{2,4})\s*(先生|女士|老师|同学|大夫|医生|教授|主任)")


@server.tool(
    "phi_scan",
    "Detect PHI-like entities (HIPAA-adjacent) in a block of text. Returns a list of findings with kind, span, matched text, confidence and reason. "
    "This is regex-only, runs 100% locally, does NOT send anything upstream. Coverage is intentionally over-inclusive — inspect the returned confidence field.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "custom_patterns": {
                "type": "array",
                "description": "Optional extra regexes to match, e.g. hospital identifiers used at your institution.",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string"},
                        "regex": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    },
                    "required": ["kind", "regex"],
                },
            },
        },
        "required": ["text"],
    },
)
def phi_scan(text: str, custom_patterns: List[Dict[str, Any]] | None = None):
    text = text or ""
    findings: List[Dict[str, Any]] = []
    seen_spans: set[Tuple[int, int]] = set()

    def _add(kind: str, span: Tuple[int, int], value: str, conf: str, why: str):
        if span in seen_spans:
            return
        seen_spans.add(span)
        findings.append({
            "kind": kind,
            "start": span[0], "end": span[1],
            "text": value,
            "confidence": conf,
            "reason": why,
        })

    for kind, pat, conf, why in _PATTERNS:
        for m in pat.finditer(text):
            _add(kind, m.span(), m.group(0), conf, why)

    for m in _AGE_HIGH.finditer(text):
        _add("AGE_OVER_89", m.span(), m.group(0), "high",
             "age >= 90 (HIPAA Safe Harbor requires collapse to '90+')")

    for m in _NAME_LATIN.finditer(text):
        _add("NAME_WITH_TITLE", m.span(), m.group(0), "high",
             "title + capitalized name — very likely a person")
    # 只有当 title-word 版本没抓到时才用宽松版：避免重复标注同一段 Dr. John Doe
    for m in _NAME_LATIN_2.finditer(text):
        _add("NAME_TITLECASE", m.span(), m.group(0), "low",
             "two consecutive Title-case words (may be a name, may be a place / brand)")
    for m in _NAME_CN.finditer(text):
        _add("NAME_CN", m.span(), m.group(0), "high",
             "Chinese surname/name + honorific")

    for cp in custom_patterns or []:
        try:
            pat = re.compile(cp["regex"])
        except re.error as e:
            findings.append({"kind": cp["kind"], "error": f"bad regex: {e}"})
            continue
        for m in pat.finditer(text):
            _add(cp["kind"], m.span(), m.group(0),
                 cp.get("confidence") or "medium", "custom pattern")

    findings.sort(key=lambda f: (f.get("start", 10**9), f.get("kind")))
    # 汇总统计给 Skill 决策用
    counts: Dict[str, int] = defaultdict(int)
    high_conf = 0
    for f in findings:
        if "start" not in f:
            continue
        counts[f["kind"]] += 1
        if f.get("confidence") == "high":
            high_conf += 1
    return {
        "findings": findings,
        "summary": {
            "total": len(findings),
            "high_confidence": high_conf,
            "by_kind": dict(counts),
        },
        "verdict": "phi_likely" if high_conf > 0 else (
            "phi_possible" if findings else "no_phi_detected"),
    }


@server.tool(
    "phi_redact",
    "Replace detected PHI with consistent placeholder tokens (e.g. [PATIENT_1], [DATE_1]). "
    "Consistency: the same original string gets the same token throughout the document. "
    "Returns redacted text plus the mapping so a trusted local reviewer can restore.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "min_confidence": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
            "custom_patterns": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["text"],
    },
)
def phi_redact(text: str, min_confidence: str = "medium",
               custom_patterns: List[Dict[str, Any]] | None = None):
    conf_rank = {"low": 0, "medium": 1, "high": 2}
    min_rank = conf_rank[min_confidence]
    scan = phi_scan(text=text, custom_patterns=custom_patterns)
    keep = [f for f in scan["findings"]
            if conf_rank.get(f.get("confidence", "low"), 0) >= min_rank
            and "start" in f]
    # 按位置倒序替换，避免偏移错乱
    keep.sort(key=lambda f: f["start"], reverse=True)
    kind_prefix = {
        "EMAIL": "EMAIL", "PHONE_INTL": "PHONE", "PHONE_US": "PHONE",
        "PHONE_CN_MOBILE": "PHONE", "SSN_US": "SSN", "CN_ID": "NATIONAL_ID",
        "DATE_ISO": "DATE", "DATE_US": "DATE", "DATE_EU": "DATE", "DATE_CN": "DATE",
        "URL": "URL", "IP_V4": "IP",
        "ZIP_US_9": "ZIP", "ZIP_US_5": "ZIP", "ZIP_CN_6": "ZIP",
        "MRN_LIKE": "MRN", "NHS_NUMBER": "NHS",
        "AGE_OVER_89": "AGE", "NAME_WITH_TITLE": "PATIENT",
        "NAME_TITLECASE": "PATIENT", "NAME_CN": "PATIENT",
    }
    counter: Dict[str, int] = defaultdict(int)
    seen_map: Dict[Tuple[str, str], str] = {}  # (prefix, original) -> token
    out = text
    mapping: List[Dict[str, str]] = []
    for f in keep:
        prefix = kind_prefix.get(f["kind"], f["kind"])
        key = (prefix, f["text"])
        if key not in seen_map:
            counter[prefix] += 1
            seen_map[key] = f"[{prefix}_{counter[prefix]}]"
        token = seen_map[key]
        out = out[: f["start"]] + token + out[f["end"] :]
        mapping.append({"token": token, "original": f["text"],
                        "kind": f["kind"], "confidence": f["confidence"]})
    return {
        "redacted": out,
        "mapping": mapping,
        "summary": scan["summary"],
        "verdict": scan["verdict"],
    }


if __name__ == "__main__":
    server.run()
