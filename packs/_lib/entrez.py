"""NCBI E-utilities 客户端（PubMed / Gene / ClinVar / dbSNP / GEO / SRA 共享）。

E-utilities 匿名限 3 req/s，带 `api_key` 上到 10 req/s；本客户端做进程内 rate limit。
key 通过环境变量 NCBI_API_KEY 注入（CSSwitch 后端从 config.pack_env 拉出后放进 MCP
server 的 env 字段），不进 argv / 不进 URL 日志。

覆盖：
  - esearch : 关键词 → uid 列表
  - esummary: uid → JSON 元数据
  - efetch  : uid → 文本/XML（本项目里用 XML+简单正则抽取，避免引 lxml/BeautifulSoup）
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

from . import http

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class _RateLimiter:
    """简单 token-bucket：每秒最多 N 次。"""
    def __init__(self, per_second: float):
        self.min_interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.last = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delta = now - self.last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self.last = time.monotonic()


def _limiter() -> _RateLimiter:
    # 有 key 就 10/s，无 key 保守到 2.5/s（比 3/s 留一点余量）。
    per_sec = 10.0 if os.environ.get("NCBI_API_KEY") else 2.5
    return _RateLimiter(per_sec)


_LIM: Optional[_RateLimiter] = None


def _lim() -> _RateLimiter:
    global _LIM
    if _LIM is None:
        _LIM = _limiter()
    return _LIM


def _base_params(extra: Dict[str, Any]) -> Dict[str, Any]:
    p = {
        "tool": "csswitch-bio-pack",
        "email": os.environ.get("NCBI_EMAIL", "csswitch@localhost.invalid"),
    }
    key = os.environ.get("NCBI_API_KEY")
    if key:
        p["api_key"] = key
    p.update(extra)
    return p


def esearch(db: str, term: str, retmax: int = 20,
            mindate: Optional[str] = None, maxdate: Optional[str] = None,
            sort: Optional[str] = None) -> Dict[str, Any]:
    _lim().wait()
    params: Dict[str, Any] = {"db": db, "term": term, "retmode": "json", "retmax": retmax}
    if mindate:
        params["mindate"] = mindate
    if maxdate:
        params["maxdate"] = maxdate
    if mindate or maxdate:
        params["datetype"] = "pdat"
    if sort:
        params["sort"] = sort
    data = http.get_json(f"{_BASE}/esearch.fcgi", params=_base_params(params))
    result = (data or {}).get("esearchresult", {})
    return {
        "count": int(result.get("count", 0)),
        "ids": result.get("idlist", []) or [],
        "query_translation": result.get("querytranslation"),
    }


def esummary(db: str, ids: List[str]) -> Dict[str, Any]:
    if not ids:
        return {}
    _lim().wait()
    params = {"db": db, "id": ",".join(ids), "retmode": "json"}
    data = http.get_json(f"{_BASE}/esummary.fcgi", params=_base_params(params))
    return (data or {}).get("result", {}) or {}


def efetch_text(db: str, ids: List[str], rettype: str, retmode: str = "text") -> str:
    if not ids:
        return ""
    _lim().wait()
    params = {"db": db, "id": ",".join(ids), "rettype": rettype, "retmode": retmode}
    return http.get_text(f"{_BASE}/efetch.fcgi", params=_base_params(params))


# ---------- PubMed 专用抽取 ----------

_PUB_TYPE_MAP = {
    # 归一化：不同 MeSH 里 publication_type 的写法 → 我们规范的证据类型。
    # 见 https://www.nlm.nih.gov/mesh/pubtypes.html
    "meta-analysis": "meta-analysis",
    "systematic review": "systematic-review",
    "randomized controlled trial": "RCT",
    "controlled clinical trial": "clinical-trial",
    "clinical trial, phase i": "clinical-trial",
    "clinical trial, phase ii": "clinical-trial",
    "clinical trial, phase iii": "clinical-trial",
    "clinical trial, phase iv": "clinical-trial",
    "clinical trial": "clinical-trial",
    "observational study": "observational",
    "cohort studies": "cohort",
    "case-control studies": "case-control",
    "case reports": "case-series",
    "review": "narrative-review",
    "comparative study": "observational",
    "multicenter study": "clinical-trial",
    "practice guideline": "guideline",
    "guideline": "guideline",
    "editorial": "editorial",
    "letter": "letter",
    "comment": "comment",
}


def classify_pub_types(pub_types: List[str]) -> str:
    """把一堆 MeSH publication_type 归一化到一个证据等级。
    多个类型时按严格性择优（meta > systematic > RCT > CT > cohort > case-control > ...）。
    """
    order = [
        "meta-analysis", "systematic-review", "RCT", "clinical-trial",
        "guideline", "cohort", "case-control", "observational",
        "case-series", "narrative-review", "editorial", "letter", "comment",
    ]
    got = set()
    for pt in pub_types:
        key = (pt or "").strip().lower()
        mapped = _PUB_TYPE_MAP.get(key)
        if mapped:
            got.add(mapped)
    for level in order:
        if level in got:
            return level
    return "unclassified"


# 从 EFetch XML 里粗抽字段（避免引 lxml；MedlineCitation 结构相对稳定）。
_RE_ARTICLE = re.compile(r"<PubmedArticle>(.*?)</PubmedArticle>", re.S)
_RE_PMID = re.compile(r"<PMID[^>]*>(\d+)</PMID>")
_RE_TITLE = re.compile(r"<ArticleTitle[^>]*>(.*?)</ArticleTitle>", re.S)
_RE_ABSTRACT = re.compile(r"<AbstractText[^>]*>(.*?)</AbstractText>", re.S)
_RE_YEAR = re.compile(r"<PubDate>.*?<Year>(\d{4})</Year>", re.S)
_RE_YEAR_MDL = re.compile(r"<MedlineDate>(\d{4})", re.S)
_RE_JOURNAL = re.compile(r"<Title>(.*?)</Title>", re.S)
_RE_DOI = re.compile(r'<ArticleId IdType="doi">(.*?)</ArticleId>', re.S)
_RE_PUBTYPE = re.compile(r"<PublicationType[^>]*>(.*?)</PublicationType>", re.S)
# MeSH 主题词：DescriptorName 是核心概念，QualifierName 是限定词。物种 / 人群 /
# 研究方向（前瞻/回顾）这些 evidence-profile 需要的信号都藏在 MeSH 里，比从
# 摘要里猜可靠得多，所以在这里就抽出来，交给 _lib/evidence_profile.py 用。
_RE_MESH = re.compile(r"<DescriptorName[^>]*>(.*?)</DescriptorName>", re.S)
_RE_AUTHOR = re.compile(
    r"<Author[^>]*>.*?<LastName>(.*?)</LastName>.*?(?:<Initials>(.*?)</Initials>)?.*?</Author>",
    re.S,
)


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def parse_pubmed_xml(xml: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for chunk in _RE_ARTICLE.findall(xml):
        m_pmid = _RE_PMID.search(chunk)
        if not m_pmid:
            continue
        pmid = m_pmid.group(1)
        title = _strip_tags(_RE_TITLE.search(chunk).group(1)) if _RE_TITLE.search(chunk) else ""
        abstract = " ".join(_strip_tags(m.group(1)) for m in _RE_ABSTRACT.finditer(chunk))
        year_m = _RE_YEAR.search(chunk) or _RE_YEAR_MDL.search(chunk)
        year = int(year_m.group(1)) if year_m else None
        journal_m = _RE_JOURNAL.search(chunk)
        journal = _strip_tags(journal_m.group(1)) if journal_m else ""
        doi_m = _RE_DOI.search(chunk)
        doi = doi_m.group(1).strip() if doi_m else None
        pub_types = [_strip_tags(m) for m in _RE_PUBTYPE.findall(chunk)]
        mesh_terms = [_strip_tags(m) for m in _RE_MESH.findall(chunk)]
        authors = []
        for m in _RE_AUTHOR.finditer(chunk):
            last, init = m.group(1), m.group(2) or ""
            authors.append(f"{last} {init}".strip())
        out.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "year": year,
            "journal": journal,
            "doi": doi,
            "authors": authors[:10],  # 别灌太多，前 10 位已足够辨识
            "publication_types": pub_types,
            "mesh_terms": mesh_terms,
            "evidence_type": classify_pub_types(pub_types),
        })
    return out
