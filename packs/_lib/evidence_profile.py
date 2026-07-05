"""证据画像抽取器 —— 把一条文献 / 试验的元数据拆成 claim-level evidence graph 需要的维度。

设计哲学（与 bio-audit 一脉相承）：
  1. **每个推断都带证据**。不返回裸值 "human"，而返回 {value, signals, confidence}，
     signals 是命中的 MeSH 词 / 摘要片段，让上游 LLM 与用户能自己判断可信度。
  2. **只从可核对的字段推**。物种优先信 MeSH（NLM 人工标引），摘要正则只作兜底并降 confidence。
  3. **抽不出就说抽不出**（value=None / "unknown"），绝不硬编一个好看的值 —— 那是二次幻觉。
  4. **纯 stdlib、纯函数、可离线**。不打网络（网络在 entrez / http 层做完），便于单测与回放。

覆盖维度：species / population / sample_size / experiment_type / disease_stage / intervention。
这些正是需求里「结论 A 由 PMID 支持，证据等级为临床 II 期 / 动物 / 体外 / 回顾性队列，
适用边界是什么」所需的全部结构化字段。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 物种 species
# ---------------------------------------------------------------------------
# MeSH 里物种是 CheckTag，标引质量高，优先信它。
_MESH_HUMAN = {"humans", "adult", "aged", "child", "adolescent", "infant",
               "middle aged", "young adult"}
_MESH_ANIMAL = {"animals", "mice", "rats", "mice, inbred c57bl", "rats, sprague-dawley",
                "disease models, animal", "zebrafish", "rabbits", "dogs", "swine",
                "macaca", "primates", "drosophila", "caenorhabditis elegans"}
_TEXT_HUMAN = ("patient", "patients", "human", "participants", "individuals", "subjects",
               "cohort", "in vivo human", "clinical")
_TEXT_ANIMAL = ("mouse", "mice", "murine", "rat ", "rats", "zebrafish", "porcine",
                "canine", "primate", "monkey", "rabbit", "xenograft", "in vivo mouse",
                "drosophila", "c. elegans")
_TEXT_INVITRO = ("cell line", "cell lines", "in vitro", "cultured cells", "hek293",
                 "hela", "spheroid", "organoid", "primary culture", "cell culture")


def species_of(text: str, mesh_terms: Optional[List[str]] = None) -> Dict[str, Any]:
    """判断研究物种。返回 {value, signals, confidence}。
    value ∈ human / animal | in-vitro | mixed | unknown。"""
    mesh = {m.lower() for m in (mesh_terms or [])}
    tl = (text or "").lower()
    signals: List[str] = []

    mesh_human = mesh & _MESH_HUMAN
    mesh_animal = mesh & _MESH_ANIMAL
    for m in sorted(mesh_human):
        signals.append(f"MeSH:{m}")
    for m in sorted(mesh_animal):
        signals.append(f"MeSH:{m}")

    text_human = [w for w in _TEXT_HUMAN if w in tl]
    text_animal = [w for w in _TEXT_ANIMAL if w in tl]
    text_invitro = [w for w in _TEXT_INVITRO if w in tl]

    has_human = bool(mesh_human) or bool(text_human)
    has_animal = bool(mesh_animal) or bool(text_animal)
    has_invitro = bool(text_invitro)

    # MeSH 命中 → 高置信；仅摘要命中 → 中置信。
    if mesh_human or mesh_animal:
        confidence = 0.9
    elif has_human or has_animal or has_invitro:
        confidence = 0.55
        signals.extend(f"abstract:{w}" for w in (text_human + text_animal + text_invitro))
    else:
        return {"value": "unknown", "signals": [], "confidence": 0.0}

    if has_human and (has_animal or has_invitro):
        value = "mixed"
    elif has_human:
        value = "human"
    elif has_animal:
        value = "animal"
    elif has_invitro:
        value = "in-vitro"
    else:
        value = "unknown"
    return {"value": value, "signals": signals[:12], "confidence": round(confidence, 2)}


# ---------------------------------------------------------------------------
# 样本量 sample_size
# ---------------------------------------------------------------------------
# 从摘要挖 n。多种写法：n = 123 / 123 patients / enrolled 456 / a total of 789。
_N_PATTERNS = [
    re.compile(r"\bn\s*=\s*([0-9][0-9,]{0,6})", re.I),
    re.compile(r"\b([0-9][0-9,]{1,6})\s+(?:patients|participants|subjects|individuals|cases|women|men|children|adults)\b", re.I),
    re.compile(r"\benrolled\s+([0-9][0-9,]{0,6})\b", re.I),
    re.compile(r"\ba total of\s+([0-9][0-9,]{0,6})\b", re.I),
    re.compile(r"\bincluded\s+([0-9][0-9,]{1,6})\b", re.I),
]


def sample_size_of(text: str, enrollment: Optional[int] = None) -> Dict[str, Any]:
    """返回 {n, source, snippet}。CT.gov enrollment 最可信，其次摘要正则。"""
    if enrollment is not None:
        try:
            n = int(enrollment)
            if n > 0:
                return {"n": n, "source": "ctgov_enrollment", "snippet": None}
        except (TypeError, ValueError):
            pass
    tl = text or ""
    best: Optional[int] = None
    snippet: Optional[str] = None
    for pat in _N_PATTERNS:
        for m in pat.finditer(tl):
            raw = m.group(1).replace(",", "")
            try:
                val = int(raw)
            except ValueError:
                continue
            # 取最大值：摘要里 "n=12" 常是子组，总样本往往更大。但排除年份区间误伤。
            if 1 <= val <= 10_000_000 and (best is None or val > best):
                best = val
                snippet = tl[max(0, m.start() - 20):m.end() + 20].strip()
    if best is None:
        return {"n": None, "source": None, "snippet": None}
    return {"n": best, "source": "abstract_regex", "snippet": snippet}


# ---------------------------------------------------------------------------
# 疾病阶段 disease_stage
# ---------------------------------------------------------------------------
_STAGE_PATTERNS = [
    (re.compile(r"\bstage\s+(0|i{1,3}v?|iv|1|2|3|4)\b", re.I), "tumor-stage"),
    (re.compile(r"\b(metastatic|advanced|locally advanced|refractory|relapsed|recurrent)\b", re.I), "advanced/late"),
    (re.compile(r"\b(early[- ]stage|resectable|newly diagnosed|treatment[- ]na[iï]ve|first[- ]line)\b", re.I), "early/first-line"),
    (re.compile(r"\b(second[- ]line|third[- ]line|pretreated|previously treated)\b", re.I), "later-line"),
    (re.compile(r"\b(neoadjuvant|adjuvant|maintenance|perioperative)\b", re.I), "peri-treatment"),
]


def disease_stage_of(text: str) -> Dict[str, Any]:
    """返回 {value, matches}。抽不到给 value=None。"""
    tl = text or ""
    matches: List[str] = []
    labels: List[str] = []
    for pat, label in _STAGE_PATTERNS:
        for m in pat.finditer(tl):
            matches.append(m.group(0))
            if label not in labels:
                labels.append(label)
    if not matches:
        return {"value": None, "matches": []}
    return {"value": " / ".join(labels), "matches": sorted(set(matches))[:8]}


# ---------------------------------------------------------------------------
# 人群 population（年龄段 / 性别 / 亚组）
# ---------------------------------------------------------------------------
_MESH_AGE = {"infant", "child", "adolescent", "adult", "middle aged", "aged",
             "young adult", "infant, newborn", "aged, 80 and over"}
_MESH_SEX = {"female", "male", "pregnancy", "postmenopause"}


def population_of(text: str, mesh_terms: Optional[List[str]] = None) -> Dict[str, Any]:
    """返回 {age_groups, sex, descriptors, signals}。以 MeSH CheckTag 为主。"""
    mesh = {m.lower() for m in (mesh_terms or [])}
    age = sorted(mesh & _MESH_AGE)
    sex = sorted(mesh & _MESH_SEX)
    # 人群限定 MeSH（非年龄非性别，但描述受试群体）
    pop_desc = sorted(m for m in mesh
                      if any(k in m for k in ("patients", "survivors", "veterans",
                                              "outpatients", "inpatients")))
    signals = [f"MeSH:{m}" for m in (age + sex + pop_desc)]
    if not (age or sex or pop_desc):
        return {"age_groups": [], "sex": [], "descriptors": [], "signals": []}
    return {"age_groups": age, "sex": sex, "descriptors": pop_desc, "signals": signals[:12]}


# ---------------------------------------------------------------------------
# 实验类型 / 研究方向：把 evidence_type + 方向 MeSH + phase 合成一个人读标签
# ---------------------------------------------------------------------------
_DIR_RETRO = {"retrospective studies", "retrospective study"}
_DIR_PROSPECT = {"prospective studies", "prospective study"}

_EV_ZH = {
    "meta-analysis": "荟萃分析", "systematic-review": "系统综述",
    "RCT": "随机对照试验", "clinical-trial": "临床试验", "guideline": "指南",
    "cohort": "队列研究", "case-control": "病例对照", "observational": "观察性研究",
    "case-series": "病例系列", "narrative-review": "叙述性综述",
    "editorial": "社论", "letter": "读者来信", "comment": "评论",
    "preprint": "预印本（未评审）", "unclassified": "未分类",
}


def experiment_type_of(
    evidence_type: Optional[str],
    mesh_terms: Optional[List[str]] = None,
    phase: Optional[str] = None,
    study_type: Optional[str] = None,
    species_value: Optional[str] = None,
) -> Dict[str, Any]:
    """合成人可读的证据等级标签，例如「临床 II 期」「回顾性队列」「动物」「体外」。
    返回 {label, evidence_type, direction, phase, basis}。"""
    mesh = {m.lower() for m in (mesh_terms or [])}
    basis: List[str] = []
    direction = None
    if mesh & _DIR_RETRO:
        direction = "retrospective"
        basis.append("MeSH:retrospective studies")
    elif mesh & _DIR_PROSPECT:
        direction = "prospective"
        basis.append("MeSH:prospective studies")

    # 临床试验 + phase → 「临床 II 期」
    parts: List[str] = []
    ev = evidence_type or "unclassified"
    if phase:
        # CT.gov phase 形如 PHASE2 / PHASE1|PHASE2
        ph = str(phase).upper().replace("PHASE", "").replace("_", " ").strip()
        roman = {"1": "I", "2": "II", "3": "III", "4": "IV"}
        ph_disp = "/".join(roman.get(p.strip(), p.strip()) for p in ph.split("|") if p.strip())
        if ph_disp:
            parts.append(f"临床 {ph_disp} 期")
            basis.append(f"phase:{phase}")
    if study_type:
        basis.append(f"study_type:{study_type}")

    if not parts:
        zh = _EV_ZH.get(ev, ev)
        if direction == "retrospective" and ev in ("cohort", "observational"):
            parts.append("回顾性队列")
        elif direction == "prospective" and ev in ("cohort", "observational"):
            parts.append("前瞻性队列")
        else:
            parts.append(zh)
    # 临床前证据用物种补齐
    if species_value in ("animal", "in-vitro") and ev in ("unclassified", "narrative-review"):
        parts = ["动物" if species_value == "animal" else "体外（细胞）"]
        basis.append(f"species:{species_value}")

    return {
        "label": " · ".join(dict.fromkeys(parts)),
        "evidence_type": ev,
        "direction": direction,
        "phase": phase,
        "basis": basis,
    }


# ---------------------------------------------------------------------------
# 顶层：把一条参考文献的元数据合成完整 evidence profile
# ---------------------------------------------------------------------------
def build_profile(meta: Dict[str, Any]) -> Dict[str, Any]:
    """输入 evidence_verify 得到的 ref meta（PubMed / CT.gov 归一化后），
    输出完整 evidence profile。meta 至少含 exists；PubMed 有 title/abstract/mesh_terms/
    evidence_type；CT.gov 有 enrollment/phase/study_type/title/official_title。"""
    if not meta.get("exists"):
        return {"exists": False}
    text = " ".join(str(meta.get(k) or "") for k in
                    ("title", "official_title", "abstract"))
    mesh = meta.get("mesh_terms") or []
    sp = species_of(text, mesh)
    profile = {
        "exists": True,
        "species": sp,
        "sample_size": sample_size_of(text, meta.get("enrollment")),
        "disease_stage": disease_stage_of(text),
        "population": population_of(text, mesh),
        "experiment": experiment_type_of(
            meta.get("evidence_type"), mesh,
            phase=meta.get("phase"), study_type=meta.get("study_type"),
            species_value=sp.get("value"),
        ),
        "year": meta.get("year"),
    }
    return profile
