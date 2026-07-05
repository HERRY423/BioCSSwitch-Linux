#!/usr/bin/env python3
"""离线合成 generator 用的 HTTP fixture。

**为什么用假 urlopen 而不是手写 fixture 文件**：fixture 的键是
sha1(method \\n canonical_url \\n body_sha1)，手算键极易错。这里 monkeypatch
`urllib.request.urlopen` 返回**我们授权的最小 body**，在 `record` 模式下跑一遍
generator 的请求路径 —— fixtures.record() 就会用**代码真实产生的 url/params**
落盘，键一定对得上。全程离线（urlopen 被替换）。

跑一次：
    python test/generators/synth_fixtures.py
产出：
    test/generators/fixtures/*.json  —— 合成 fixture（脱敏，可入 git）

真实 fidelity fixture 用 `make_fixtures.py --live` 从网络录（覆盖同名文件）。
"""

from __future__ import annotations

import io
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "packs"))

from _lib import fixtures  # noqa: E402

_FIX_DIR = Path(__file__).parent / "fixtures"


# ── 授权的最小响应体（按 URL 子串 + 关键 param 匹配）─────────────────────────
# 每条：matcher(url, params) → response_json（dict / list / str）

def _mesh_esearch(url: str, p: Dict[str, Any]) -> Optional[Any]:
    if "esearch.fcgi" in url and p.get("db") == "mesh":
        term = (p.get("term") or "").lower()
        # 给几个常见 PICO 词一个稳定的假 UID
        uid_map = {
            "type 2 diabetes": "68003924",  # Diabetes Mellitus, Type 2
            "diabetes": "68003920",
            "metformin": "68008687",
            "cardiovascular": "68002318",
            "placebo": "68010919",
        }
        for k, uid in uid_map.items():
            if k in term:
                return {"esearchresult": {"count": "1", "idlist": [uid],
                                          "querytranslation": term}}
        return {"esearchresult": {"count": "0", "idlist": []}}
    return None


def _mesh_esummary(url: str, p: Dict[str, Any]) -> Optional[Any]:
    if "esummary.fcgi" in url and p.get("db") == "mesh":
        ids = (p.get("id") or "").split(",")
        name_map = {
            "68003924": "Diabetes Mellitus, Type 2",
            "68003920": "Diabetes Mellitus",
            "68008687": "Metformin",
            "68002318": "Cardiovascular Diseases",
            "68010919": "Placebos",
        }
        result = {"uids": ids}
        for uid in ids:
            result[uid] = {
                "uid": uid,
                "ds_meshui": name_map.get(uid, f"MeSH {uid}"),
                "ds_meshterms": name_map.get(uid, f"MeSH {uid}"),
                "title": name_map.get(uid, f"MeSH {uid}"),
                "ds_meshtreenumberlist": ["C18.452.394.750.149"],
                "ds_scopenote": "synthetic fixture scope note",
                "ds_entryterms": [],
            }
        return {"result": result}
    return None


def _hgnc(url: str, p: Dict[str, Any]) -> Optional[Any]:
    if "genenames.org/fetch/symbol/" in url:
        symbol = url.rstrip("/").split("/")[-1].split("?")[0]
        db = {
            "BRCA1": {
                "hgnc_id": "HGNC:1100", "symbol": "BRCA1",
                "name": "BRCA1 DNA repair associated",
                "uniprot_ids": ["P38398"], "ensembl_gene_id": "ENSG00000012048",
                "entrez_id": "672", "locus_group": "protein-coding gene",
            },
            "EGFR": {
                "hgnc_id": "HGNC:3236", "symbol": "EGFR",
                "name": "epidermal growth factor receptor",
                "uniprot_ids": ["P00533"], "ensembl_gene_id": "ENSG00000146648",
                "entrez_id": "1956", "locus_group": "protein-coding gene",
            },
        }
        doc = db.get(symbol)
        return {"response": {"docs": [doc] if doc else []}}
    return None


def _uniprot(url: str, p: Dict[str, Any]) -> Optional[Any]:
    if "rest.uniprot.org/uniprotkb/" in url and url.endswith(".json"):
        acc = url.rstrip("/").split("/")[-1].replace(".json", "")
        db = {
            "P38398": {
                "primaryAccession": "P38398",
                "proteinDescription": {"recommendedName": {"fullName": {"value": "Breast cancer type 1 susceptibility protein"}}},
                "genes": [{"geneName": {"value": "BRCA1"}}],
                "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
                "sequence": {"length": 1863},
                "keywords": [{"name": "DNA damage"}, {"name": "DNA repair"},
                             {"name": "Ubl conjugation pathway"}],
                "comments": [{"commentType": "SIMILARITY",
                              "texts": [{"value": "Belongs to the RING-type zinc finger family."}]}],
            },
            "P00533": {
                "primaryAccession": "P00533",
                "proteinDescription": {"recommendedName": {"fullName": {"value": "Epidermal growth factor receptor"}}},
                "genes": [{"geneName": {"value": "EGFR"}}],
                "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
                "sequence": {"length": 1210},
                "keywords": [{"name": "Kinase"}, {"name": "Tyrosine-protein kinase"},
                             {"name": "Receptor"}, {"name": "Transferase"}],
                "comments": [{"commentType": "SIMILARITY",
                              "texts": [{"value": "Belongs to the protein kinase superfamily."}]}],
            },
        }
        return db.get(acc, {})
    return None


def _chembl_target_search(url: str, p: Dict[str, Any]) -> Optional[Any]:
    if "chembl" in url and "target/search.json" in url:
        q = (p.get("q") or "").upper()
        db = {
            "BRCA1": {"target_chembl_id": "CHEMBL5334", "pref_name": "Breast cancer type 1 susceptibility protein"},
            "EGFR": {"target_chembl_id": "CHEMBL203", "pref_name": "Epidermal growth factor receptor erbB1"},
        }
        t = db.get(q)
        return {"targets": [t] if t else []}
    return None


def _chembl_activity(url: str, p: Dict[str, Any]) -> Optional[Any]:
    if "chembl" in url and "activity.json" in url:
        tid = p.get("target_chembl_id")
        counts = {"CHEMBL203": 4200, "CHEMBL5334": 3}
        return {"activities": [], "page_meta": {"total_count": counts.get(tid, 0)}}
    return None


def _ot_gql(url: str, p: Dict[str, Any], body: Optional[bytes]) -> Optional[Any]:
    if "platform.opentargets.org" in url:
        # body 里带 ensemblId variable
        try:
            payload = json.loads(body.decode()) if body else {}
        except Exception:
            payload = {}
        ens = (payload.get("variables") or {}).get("id", "")
        db = {
            "ENSG00000146648": {  # EGFR
                "data": {"target": {"id": "ENSG00000146648", "approvedSymbol": "EGFR",
                    "approvedName": "epidermal growth factor receptor",
                    "tractability": [
                        {"modality": "SM", "label": "Approved Drug", "value": True},
                        {"modality": "SM", "label": "Structure with Ligand", "value": True},
                        {"modality": "AB", "label": "Approved Drug", "value": True},
                    ],
                    "knownDrugs": {"count": 320, "uniqueDrugs": 45, "uniqueTargets": 1, "rows": []}}}},
            "ENSG00000012048": {  # BRCA1
                "data": {"target": {"id": "ENSG00000012048", "approvedSymbol": "BRCA1",
                    "approvedName": "BRCA1 DNA repair associated",
                    "tractability": [{"modality": "SM", "label": "Structure", "value": False}],
                    "knownDrugs": {"count": 0, "uniqueDrugs": 0, "uniqueTargets": 0, "rows": []}}}},
        }
        return db.get(ens, {"data": {"target": None}})
    return None


def _ctgov(url: str, p: Dict[str, Any]) -> Optional[Any]:
    if "clinicaltrials.gov/api/v2/studies" in url:
        # 返回一个 2 试验的小集合
        return {
            "totalCount": 2,
            "studies": [
                {"protocolSection": {
                    "identificationModule": {"nctId": "NCT01111111", "briefTitle": "Pembrolizumab in NSCLC Phase 3"},
                    "statusModule": {"overallStatus": "RECRUITING"},
                    "designModule": {"phases": ["PHASE3"], "studyType": "INTERVENTIONAL",
                                     "enrollmentInfo": {"count": 600}},
                    "conditionsModule": {"conditions": ["Non-small Cell Lung Cancer"]},
                    "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "Pembrolizumab"}]},
                    "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Merck Sharp & Dohme LLC"}},
                    "contactsLocationsModule": {"locations": [
                        {"facility": "Site A", "city": "Boston", "country": "United States", "status": "RECRUITING"}]},
                    "outcomesModule": {"primaryOutcomes": [{"measure": "Overall Survival"}],
                                       "secondaryOutcomes": [{"measure": "PFS"}]},
                }},
                {"protocolSection": {
                    "identificationModule": {"nctId": "NCT02222222", "briefTitle": "Nivolumab NSCLC Phase 2"},
                    "statusModule": {"overallStatus": "COMPLETED"},
                    "designModule": {"phases": ["PHASE2"], "studyType": "INTERVENTIONAL",
                                     "enrollmentInfo": {"count": 120}},
                    "conditionsModule": {"conditions": ["NSCLC"]},
                    "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "Nivolumab"}]},
                    "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Bristol-Myers Squibb"}},
                    "contactsLocationsModule": {"locations": [
                        {"facility": "Site B", "city": "Paris", "country": "France", "status": "COMPLETED"}]},
                    "outcomesModule": {"primaryOutcomes": [{"measure": "Objective Response Rate"}],
                                       "secondaryOutcomes": [{"measure": "Overall Survival"}]},
                }},
            ],
            "nextPageToken": None,
        }
    return None


_MATCHERS: List[Callable] = [
    lambda u, p, b: _mesh_esearch(u, p),
    lambda u, p, b: _mesh_esummary(u, p),
    lambda u, p, b: _hgnc(u, p),
    lambda u, p, b: _uniprot(u, p),
    lambda u, p, b: _chembl_target_search(u, p),
    lambda u, p, b: _chembl_activity(u, p),
    lambda u, p, b: _ot_gql(u, p, b),
    lambda u, p, b: _ctgov(u, p),
]


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def _parse_qs_from_url(url: str) -> Dict[str, Any]:
    import urllib.parse
    q = urllib.parse.urlsplit(url).query
    out = {}
    for k, v in urllib.parse.parse_qs(q).items():
        out[k] = v[0] if len(v) == 1 else v
    return out


def _fake_urlopen(req, timeout=None):  # noqa: ARG001
    url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
    body = req.data
    params = _parse_qs_from_url(url)
    for m in _MATCHERS:
        resp = m(url, params, body)
        if resp is not None:
            return _FakeResp(json.dumps(resp).encode("utf-8"))
    # 没匹配到 → 返回空 JSON，让 generator 走空分支（也会被 record）
    sys.stderr.write(f"[synth] 未匹配 URL（返回空）：{url[:120]}\n")
    return _FakeResp(b"{}")


def main() -> int:
    _FIX_DIR.mkdir(parents=True, exist_ok=True)
    # record 模式：真实请求路径产生的 key + 我们授权的 body
    fixtures.activate(_FIX_DIR, mode="record")
    orig = urllib.request.urlopen
    urllib.request.urlopen = _fake_urlopen  # type: ignore
    try:
        # 驱动每个 generator 的核心请求路径
        sys.path.insert(0, str(_ROOT / "packs" / "bio-workflows" / "generators"))
        import importlib.util

        def _load(rel):
            p = _ROOT / "packs" / "bio-workflows" / "generators" / rel
            spec = importlib.util.spec_from_file_location(rel.replace(".py", ""), p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

        sr = _load("sr_pico_builder.py")
        td = _load("td_druggability.py")
        ct = _load("ct_landscape.py")

        print("[synth] sr_pico_builder …")
        sr.build_pubmed_query(population="adults with type 2 diabetes",
                              intervention="metformin monotherapy",
                              comparator="placebo",
                              outcome="cardiovascular events", study_type="RCT")
        print("[synth] td_druggability EGFR …")
        td.evaluate("EGFR")
        print("[synth] td_druggability BRCA1 …")
        td.evaluate("BRCA1")
        print("[synth] ct_landscape …")
        studies = ct._fetch_all("non-small cell lung cancer", "pembrolizumab OR nivolumab", None, 1)
        ct.build_landscape(studies)
    finally:
        urllib.request.urlopen = orig  # type: ignore
        st = fixtures.stats()
        fixtures.deactivate()
    print(f"[synth] 完成，录制 {st['recorded']} 条 fixture → {_FIX_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
