#!/usr/bin/env python3
"""GRADE / SoF 引擎 MCP —— 给每个 outcome 评「证据确定性有多高、为什么」。

GRADE（Grading of Recommendations Assessment, Development and Evaluation）是顶级
医学（Cochrane / WHO / UpToDate / 各国指南）评证据确定性的事实标准。核心：**不是给
一篇文献评级，而是给一个 outcome 的整体证据体（body of evidence）评级**，产出四档
确定性 High / Moderate / Low / Very Low，并逐条说明升/降级理由。

本引擎的分工（与 bio-audit 一贯的「工具定死算术、模型给判断」原则一致）：
  - **模型**：读文献后对 5 个降级域 + 3 个升级域给出判断（serious / very serious + 理由）。
    这些需要读研究才能判断（如"结果不一致"），工具替代不了。
  - **工具**：把设计→起始档、升降级→算术**确定性地**算完，产出确定性符号（⊕⊕⊕⊝）+
    结构化理由 + GRADE 规则守卫（RCT 不能升级、无理由的降级要警告……），并渲染 SoF 表。

这样模型无法含糊地说"中等确定性"——它必须逐域声明"为什么"，工具把算术锁死、把规则违背暴露。

工具：
  grade_outcome      — 单个 outcome 的确定性评级（起始档 + 降级 + 升级 → 四档 + 逐域理由）
  grade_sof_table    — 跨 outcome 汇总成 Summary of Findings 表（Markdown）
  grade_explain      — 返回 GRADE 域定义速查（透明度，便于模型/用户对齐判断标准）
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib.server import MCPServer  # noqa: E402


server = MCPServer("bio-audit-grade", "0.3.0")


# ---------------------------------------------------------------------------
# 起始确定性：由研究设计决定
# ---------------------------------------------------------------------------
# GRADE：RCT 体系起于 High(4)；非随机/观察性起于 Low(2)；病例系列/机制起于 Very Low(1)。
# 关键：**meta-analysis / systematic-review 本身不决定起始档**——取决于纳入研究设计；
# **"clinical-trial" 是模糊词**，必须拆成随机对照(High) vs 单臂/非随机(Low)。二者都不许默认 High。
_DESIGN_START = {
    # —— RCT 体系 → High(4) ——
    "rct": 4, "randomized": 4, "randomised": 4,
    "randomized-controlled-trial": 4, "randomised-controlled-trial": 4,
    "systematic-review-of-rcts": 4, "meta-analysis-of-rcts": 4,
    # —— 非随机干预 / 观察性 → Low(2) ——
    "non-randomized-trial": 2, "nonrandomized": 2, "non-randomised-trial": 2,
    "single-arm-trial": 2, "single-arm": 2, "uncontrolled-trial": 2,
    "quasi-experimental": 2, "phase-1": 2, "phase-2-single-arm": 2, "nrsi": 2,
    "observational": 2, "cohort": 2, "prospective-cohort": 2, "retrospective-cohort": 2,
    "case-control": 2, "cross-sectional": 2, "nested-case-control": 2,
    # —— 更弱 → Very Low(1) ——
    "case-series": 1, "case-report": 1, "mechanistic": 1, "in-vitro": 1,
    "animal": 1, "preclinical": 1,
}
# 只有"真·RCT 体系"才禁止升级；单臂/非随机试验按观察性，可升级。
_DESIGN_IS_RCT = {"rct", "randomized", "randomised", "randomized-controlled-trial",
                  "randomised-controlled-trial", "systematic-review-of-rcts",
                  "meta-analysis-of-rcts"}
# 需要拆类型 / 需要 underlying_design 才能定档的模糊设计词。
_AMBIGUOUS_TRIAL = {"clinical-trial", "clinical trial", "trial", "interventional"}
_META_LIKE = {"meta-analysis", "systematic-review", "meta analysis", "systematic review",
              "sr", "ma"}

_LEVEL_NAME = {4: "High", 3: "Moderate", 2: "Low", 1: "Very Low"}
_LEVEL_SYMBOL = {4: "⊕⊕⊕⊕", 3: "⊕⊕⊕⊝", 2: "⊕⊕⊝⊝", 1: "⊕⊝⊝⊝"}
_LEVEL_ZH = {4: "高", 3: "中", 2: "低", 1: "极低"}

_DOWNGRADE_DOMAINS = ["risk_of_bias", "inconsistency", "indirectness",
                      "imprecision", "publication_bias"]
_DOWNGRADE_ZH = {
    "risk_of_bias": "偏倚风险", "inconsistency": "不一致性", "indirectness": "间接性",
    "imprecision": "不精确性", "publication_bias": "发表偏倚",
}
_UPGRADE_DOMAINS = ["large_effect", "dose_response", "plausible_confounding"]
_UPGRADE_ZH = {
    "large_effect": "大效应量", "dose_response": "剂量-反应梯度",
    "plausible_confounding": "残余混杂会削弱效应",
}

_SERIOUS_POINTS = {"not_serious": 0, "none": 0, "serious": -1, "very_serious": -2}
_LARGE_POINTS = {"none": 0, "large": 1, "very_large": 2}
_PRESENT_POINTS = {"none": 0, "present": 1, "would_reduce": 1}

# Cochrane RoB 2-style signalling domains for randomized trials.  We keep the
# data model generic enough to accept ROBINS-I / custom domains too, but these
# names make the exported dossier easy to align with RoB 2 templates.
_ROB2_DOMAINS = [
    "randomization_process",
    "deviations_from_intended_interventions",
    "missing_outcome_data",
    "measurement_of_outcome",
    "selection_of_reported_result",
]
_ROB_POINTS = {
    "low": 0.0,
    "low_risk": 0.0,
    "not_serious": 0.0,
    "some_concerns": 1.0,
    "some concern": 1.0,
    "unclear": 1.0,
    "serious": 1.0,
    "high": 2.0,
    "high_risk": 2.0,
    "very_serious": 2.0,
    "critical": 2.0,
}


def _normalise_rating(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _weight_for_study(study: Dict[str, Any]) -> float:
    for key in ("n_analyzed", "n_randomized", "n_participants", "n"):
        try:
            v = float(study.get(key) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            return v
    return 1.0


def _study_design_start(study: Dict[str, Any]) -> tuple[int, bool]:
    start, _, is_rct = _start_certainty(
        str(study.get("design") or study.get("study_design") or ""),
        study.get("underlying_design"),
    )
    return start, is_rct


def _body_start_certainty(
    fallback_design: str,
    underlying_design: Optional[str],
    studies: Optional[List[Dict[str, Any]]] = None,
) -> tuple[int, List[str], bool, Dict[str, Any]]:
    """Estimate starting certainty from the body composition, not one label."""
    if not studies:
        start, warns, is_rct = _start_certainty(fallback_design, underlying_design)
        return start, warns, is_rct, {
            "model": "single_design_label",
            "design": fallback_design,
            "underlying_design": underlying_design,
            "start_score": start,
        }

    weighted_scores: List[tuple[int, float, bool, str]] = []
    for study in studies:
        score, is_rct = _study_design_start(study)
        weighted_scores.append((
            score,
            _weight_for_study(study),
            is_rct,
            str(study.get("design") or study.get("study_design") or "unknown").lower(),
        ))

    total_w = sum(w for _, w, _, _ in weighted_scores) or 1.0
    mean_score = sum(score * w for score, w, _, _ in weighted_scores) / total_w
    # Conservative discretisation: a mixed RCT/observational body can start at
    # Moderate rather than pretending all evidence has RCT-level certainty.
    if mean_score >= 3.5:
        start = 4
    elif mean_score >= 2.5:
        start = 3
    elif mean_score >= 1.5:
        start = 2
    else:
        start = 1
    rct_weight = sum(w for _, w, is_rct, _ in weighted_scores if is_rct) / total_w
    design_mix = Counter(design for _, _, _, design in weighted_scores)
    warnings: List[str] = []
    if len(design_mix) > 1:
        warnings.append(
            "证据体纳入了混合设计；起始确定性按样本量加权的证据体组成估计，"
            "请确认没有把 RCT 与观察性研究机械合并。"
        )
    return start, warnings, rct_weight >= 0.75, {
        "model": "sample_size_weighted_body_design",
        "mean_start_score": round(mean_score, 3),
        "start_score": start,
        "rct_weight": round(rct_weight, 3),
        "design_mix": dict(design_mix),
        "n_studies": len(studies),
        "weight_total": total_w,
    }


def _study_rob_assessment(study: Dict[str, Any], outcome_id: Optional[str] = None) -> Dict[str, Any]:
    per_outcome = study.get("outcome_risk_of_bias") or study.get("outcome_rob") or {}
    if outcome_id and isinstance(per_outcome, dict) and outcome_id in per_outcome:
        rob = per_outcome.get(outcome_id) or {}
    else:
        rob = study.get("risk_of_bias") or study.get("rob") or {}
    if not isinstance(rob, dict):
        rob = {"overall": rob}
    return rob


def _rob_points(rob: Dict[str, Any]) -> tuple[float, str, Dict[str, Any]]:
    domains = rob.get("domains") if isinstance(rob.get("domains"), dict) else {}
    domain_scores = []
    normalized_domains: Dict[str, Any] = {}
    for dom, rating in domains.items():
        norm = _normalise_rating(rating)
        pts = _ROB_POINTS.get(norm, 1.0)
        domain_scores.append(pts)
        normalized_domains[dom] = {"rating": rating, "points": pts}
    overall = _normalise_rating(rob.get("overall") or rob.get("judgement") or rob.get("judgment"))
    if overall:
        overall_points = _ROB_POINTS.get(overall, max(domain_scores or [1.0]))
    elif domain_scores:
        overall_points = max(domain_scores)
        overall = max(normalized_domains.items(), key=lambda kv: kv[1]["points"])[1]["rating"]
    else:
        overall_points = 1.0
        overall = "unclear"
    return float(overall_points), str(overall), normalized_domains


def _derive_risk_of_bias_domain(
    studies: List[Dict[str, Any]],
    outcome_id: Optional[str] = None,
) -> Dict[str, Any]:
    if not studies:
        return {
            "rating": "serious",
            "reason": "未提供 study-level RoB；无法量化偏倚风险，保守按 serious。",
            "evidence": {"model": "missing_study_level_rob"},
        }
    rows = []
    total_w = 0.0
    weighted = 0.0
    for study in studies:
        rob = _study_rob_assessment(study, outcome_id)
        pts, overall, domains = _rob_points(rob)
        weight = _weight_for_study(study)
        total_w += weight
        weighted += pts * weight
        rows.append({
            "study_id": study.get("study_id") or study.get("id") or study.get("citation") or "<unknown>",
            "weight": weight,
            "overall": overall,
            "points": pts,
            "domains": domains,
            "reason": rob.get("reason") or rob.get("support_for_judgement") or "",
        })
    mean = weighted / (total_w or 1.0)
    if mean >= 1.5:
        rating = "very_serious"
    elif mean >= 0.5:
        rating = "serious"
    else:
        rating = "not_serious"
    high_weight = sum(r["weight"] for r in rows if r["points"] >= 2.0) / (total_w or 1.0)
    concern_weight = sum(r["weight"] for r in rows if r["points"] >= 1.0) / (total_w or 1.0)
    reason = (
        f"study-level RoB 加权均值={mean:.2f}；"
        f"high-risk 权重={high_weight:.0%}，some-concerns-or-worse 权重={concern_weight:.0%}。"
    )
    return {
        "rating": rating,
        "reason": reason,
        "evidence": {
            "model": "sample_size_weighted_rob2",
            "outcome_id": outcome_id,
            "weighted_mean": round(mean, 3),
            "high_risk_weight": round(high_weight, 3),
            "concern_or_worse_weight": round(concern_weight, 3),
            "studies": rows,
        },
    }


def _start_certainty(design: str, underlying_design: Optional[str]):
    """返回 (起始档 int, warnings list, is_rct_body bool)。
    刻意不给 meta/SR、模糊 clinical-trial 默认 High——那是原来的 bug。"""
    d = (design or "").strip().lower()
    u = (underlying_design or "").strip().lower()
    warns: List[str] = []

    # meta-analysis / systematic-review：起始档取决于纳入研究设计
    if d in _META_LIKE:
        if not u:
            warns.append("meta-analysis / systematic-review 的起始确定性取决于纳入研究设计，"
                         "未声明 underlying_design → 保守按 observational(Low) 处理；"
                         "请补 underlying_design=rct 或 observational")
            return 2, warns, False
        if u in _DESIGN_START:
            is_rct = u in _DESIGN_IS_RCT or u in ("rct", "randomized")
            return _DESIGN_START[u], warns, is_rct
        warns.append(f"underlying_design='{underlying_design}' 无法识别 → 保守按 observational(Low)")
        return 2, warns, False

    # 模糊的 "clinical-trial"：必须拆随机与否
    if d in _AMBIGUOUS_TRIAL:
        warns.append("'clinical-trial' 未指明是否随机对照——GRADE 需拆类型："
                     "随机对照(RCT)→High，单臂/非随机→observational(Low)。"
                     "已保守按非随机(Low) 处理；请把 design 改成 rct / single-arm-trial / "
                     "non-randomized-trial 等明确类型")
        return 2, warns, False

    if d in _DESIGN_START:
        return _DESIGN_START[d], warns, (d in _DESIGN_IS_RCT)

    warns.append(f"design='{design}' 无法识别 → 保守按 observational(Low)；"
                 "请用明确设计词（rct / cohort / case-control / single-arm-trial …）")
    return 2, warns, False


@server.tool(
    "grade_outcome",
    "Rate the CERTAINTY OF EVIDENCE for ONE outcome using GRADE. Starting certainty is set by study "
    "design (RCT→High, non-randomized/single-arm/observational→Low, case-series→Very Low). NOTE: bare "
    "'clinical-trial' is ambiguous — pass rct / single-arm-trial / non-randomized-trial. meta-analysis / "
    "systematic-review do NOT default to High — pass underlying_design (rct|observational) or they are "
    "treated conservatively as Low with a warning. The MODEL supplies per-domain judgments (with reasons) for "
    "5 downgrade domains (risk_of_bias, inconsistency, indirectness, imprecision, publication_bias) and, "
    "for observational bodies only, 3 upgrade domains (large_effect, dose_response, plausible_confounding). "
    "The TOOL does the GRADE arithmetic deterministically, returns the four-level certainty "
    "(High/Moderate/Low/Very Low with ⊕ symbols), a per-domain justification of WHY, and GRADE rule "
    "warnings (e.g. RCTs can't be upgraded; serious downgrades need a reason).",
    {
        "type": "object",
        "properties": {
            "outcome": {"type": "string", "description": "The specific outcome, e.g. 'all-cause mortality at 12 months'"},
            "design": {"type": "string",
                       "description": "rct / observational / cohort / case-control / case-series / meta-analysis / systematic-review"},
            "underlying_design": {"type": "string",
                                  "description": "For meta-analysis/SR: the design of included studies (rct/observational)"},
            "n_studies": {"type": "integer"},
            "n_participants": {"type": "integer"},
            "domains": {
                "type": "object",
                "description": "Downgrade judgments. Each: {rating: not_serious|serious|very_serious, reason: str}.",
                "properties": {
                    "risk_of_bias": {"type": "object"},
                    "inconsistency": {"type": "object"},
                    "indirectness": {"type": "object"},
                    "imprecision": {"type": "object"},
                    "publication_bias": {"type": "object"},
                },
            },
            "upgrades": {
                "type": "object",
                "description": "Observational only. large_effect:{rating:none|large|very_large}, "
                               "dose_response:{rating:none|present}, plausible_confounding:{rating:none|would_reduce}.",
            },
            "effect": {
                "type": "object",
                "description": "Optional effect for SoF: {measure: 'RR'|'HR'|'OR'|'MD', value, ci_low, ci_high}.",
            },
            "evidence_body": {
                "type": "object",
                "description": "Optional structured body of evidence: {studies:[{study_id, design, n_participants, risk_of_bias|outcome_risk_of_bias}]}. If present, starting certainty and risk_of_bias can be derived from the whole body.",
            },
        },
        "required": ["outcome", "design", "domains"],
    },
)
def grade_outcome(outcome: str, design: str, domains: Dict[str, Any],
                  underlying_design: Optional[str] = None,
                  n_studies: Optional[int] = None, n_participants: Optional[int] = None,
                  upgrades: Optional[Dict[str, Any]] = None,
                  effect: Optional[Dict[str, Any]] = None,
                  evidence_body: Optional[Dict[str, Any]] = None):
    body_studies = []
    outcome_id = outcome
    if isinstance(evidence_body, dict):
        body_studies = [
            s for s in (evidence_body.get("studies") or [])
            if isinstance(s, dict)
        ]
        outcome_id = evidence_body.get("outcome_id") or outcome
    start, start_warns, is_rct, start_model = _body_start_certainty(
        design,
        underlying_design,
        body_studies,
    )
    warnings: List[str] = list(start_warns)
    domains = dict(domains or {})
    evidence_body_model: Dict[str, Any] = {"starting_certainty": start_model}
    if body_studies:
        evidence_body_model["risk_of_bias"] = _derive_risk_of_bias_domain(body_studies, outcome_id)
        rob = domains.get("risk_of_bias") or {}
        if not isinstance(rob, dict) or not rob.get("rating"):
            domains["risk_of_bias"] = evidence_body_model["risk_of_bias"]

    # ---- 降级 ----
    downgrade_total = 0
    downgrade_detail: List[Dict[str, Any]] = []
    for dom in _DOWNGRADE_DOMAINS:
        d = (domains or {}).get(dom) or {}
        rating = (d.get("rating") or "not_serious").lower()
        pts = _SERIOUS_POINTS.get(rating, 0)
        reason = d.get("reason") or ""
        if pts < 0 and not reason:
            warnings.append(f"{_DOWNGRADE_ZH[dom]}判为 {rating} 却未给理由——GRADE 要求每次降级都说明「为什么」")
        downgrade_total += pts
        downgrade_detail.append({"domain": dom, "domain_zh": _DOWNGRADE_ZH[dom],
                                 "rating": rating, "points": pts, "reason": reason})

    # ---- 升级（仅观察性、且无降级时才考虑）----
    upgrade_total = 0
    upgrade_detail: List[Dict[str, Any]] = []
    ups = upgrades or {}
    if ups:
        if is_rct:
            warnings.append("研究设计属 RCT 体系，GRADE 规定不可升级——已忽略 upgrades")
        else:
            if downgrade_total < 0:
                warnings.append("存在降级项时通常不再升级（GRADE：升级仅用于无严重局限的观察性证据）——请复核")
            le = (ups.get("large_effect") or {})
            le_pts = _LARGE_POINTS.get((le.get("rating") or "none").lower(), 0)
            dr = (ups.get("dose_response") or {})
            dr_pts = _PRESENT_POINTS.get((dr.get("rating") or "none").lower(), 0)
            pc = (ups.get("plausible_confounding") or {})
            pc_pts = _PRESENT_POINTS.get((pc.get("rating") or "none").lower(), 0)
            for name, pts, obj in [("large_effect", le_pts, le), ("dose_response", dr_pts, dr),
                                   ("plausible_confounding", pc_pts, pc)]:
                if pts > 0:
                    upgrade_detail.append({"domain": name, "domain_zh": _UPGRADE_ZH[name],
                                           "points": pts, "reason": obj.get("reason") or ""})
            upgrade_total = le_pts + dr_pts + pc_pts

    final = start + downgrade_total + upgrade_total
    final = max(1, min(4, final))

    # 不精确性常与样本量相关：给个软提示
    if n_participants is not None and n_participants < 300 and \
            (domains.get("imprecision", {}) or {}).get("rating", "not_serious") == "not_serious":
        warnings.append(f"总样本 {n_participants} < 300，通常需考虑不精确性（imprecision）是否 serious")

    certainty_reasons = [
        f"起始档：{design} → {_LEVEL_NAME[start]}（{_LEVEL_ZH[start]}）"]
    for dd in downgrade_detail:
        if dd["points"] < 0:
            certainty_reasons.append(
                f"↓ {dd['domain_zh']} {dd['rating']}（{dd['points']}）：{dd['reason'] or '未说明'}")
    for ud in upgrade_detail:
        certainty_reasons.append(f"↑ {ud['domain_zh']}（+{ud['points']}）：{ud['reason'] or '未说明'}")

    return {
        "outcome": outcome,
        "certainty": _LEVEL_NAME[final],
        "certainty_zh": _LEVEL_ZH[final],
        "symbol": _LEVEL_SYMBOL[final],
        "score": final,
        "starting_certainty": _LEVEL_NAME[start],
        "downgrade_total": downgrade_total,
        "upgrade_total": upgrade_total,
        "downgrade_detail": downgrade_detail,
        "upgrade_detail": upgrade_detail,
        "why": certainty_reasons,
        "warnings": warnings,
        "evidence_body_model": evidence_body_model,
        "n_studies": n_studies,
        "n_participants": n_participants,
        "effect": effect,
    }


def _studies_for_outcome(studies: List[Dict[str, Any]], outcome_id: str) -> List[Dict[str, Any]]:
    selected = []
    for study in studies:
        declared = study.get("outcomes") or study.get("outcome_ids")
        if not declared or outcome_id in declared:
            selected.append(study)
    return selected


def _outcome_domains_from_dossier(outcome: Dict[str, Any], studies: List[Dict[str, Any]]) -> Dict[str, Any]:
    domains = dict(outcome.get("domains") or {})
    outcome_id = outcome.get("id") or outcome.get("outcome") or outcome.get("name") or ""
    if studies and not (domains.get("risk_of_bias") or {}).get("rating"):
        domains["risk_of_bias"] = _derive_risk_of_bias_domain(studies, outcome_id)
    return domains


@server.tool(
    "grade_evidence_dossier",
    "Build and grade a structured GRADE evidence dossier. The dossier models a BODY OF EVIDENCE: "
    "one PICO/question, shared included studies with RoB 2-style study/outcome risk-of-bias records, "
    "and multiple critical/important outcomes. The tool derives body-level starting certainty from the "
    "study mix, aggregates study-level risk of bias into a GRADE domain, grades every outcome, and emits "
    "a GRADEpro-like evidence profile / Summary of Findings payload plus Markdown.",
    {
        "type": "object",
        "properties": {
            "dossier": {
                "type": "object",
                "description": "Structured dossier: {question|pico, studies:[{study_id, design, n_participants, risk_of_bias:{overall,domains,reason}, outcomes}], outcomes:[{id,outcome,criticality,domains,upgrades,effect}]}.",
            },
            "language": {"type": "string", "enum": ["zh", "en"], "default": "zh"},
        },
        "required": ["dossier"],
    },
)
def grade_evidence_dossier(dossier: Dict[str, Any], language: str = "zh"):
    studies = [s for s in (dossier or {}).get("studies", []) if isinstance(s, dict)]
    outcomes = [o for o in (dossier or {}).get("outcomes", []) if isinstance(o, dict)]
    warnings: List[str] = []
    if not outcomes:
        return {
            "schema": "bio-audit/grade-evidence-dossier/1",
            "errors": ["dossier.outcomes is required and must contain at least one outcome"],
            "warnings": warnings,
        }
    if not studies:
        warnings.append("dossier.studies 为空；每个 outcome 将只能按显式 domains 评级，无法正式建模证据体。")

    graded = []
    outcome_profiles = []
    for outcome in outcomes:
        oid = outcome.get("id") or outcome.get("outcome") or outcome.get("name") or "outcome"
        label = outcome.get("outcome") or outcome.get("name") or oid
        scoped_studies = _studies_for_outcome(studies, oid)
        n_p = outcome.get("n_participants")
        if n_p is None and scoped_studies:
            n_p = int(sum(_weight_for_study(s) for s in scoped_studies))
        domains = _outcome_domains_from_dossier(outcome, scoped_studies)
        graded_outcome = grade_outcome(
            outcome=label,
            design=outcome.get("design") or "body-of-evidence",
            underlying_design=outcome.get("underlying_design"),
            domains=domains,
            upgrades=outcome.get("upgrades"),
            effect=outcome.get("effect"),
            n_studies=outcome.get("n_studies") or len(scoped_studies) or None,
            n_participants=n_p,
            evidence_body={"outcome_id": oid, "studies": scoped_studies},
        )
        graded_outcome["outcome_id"] = oid
        graded_outcome["criticality"] = outcome.get("criticality", "important")
        graded.append(graded_outcome)
        outcome_profiles.append({
            "outcome_id": oid,
            "outcome": label,
            "criticality": outcome.get("criticality", "important"),
            "included_studies": [
                s.get("study_id") or s.get("id") or s.get("citation") or "<unknown>"
                for s in scoped_studies
            ],
            "certainty": graded_outcome["certainty"],
            "certainty_score": graded_outcome["score"],
            "domains": graded_outcome["downgrade_detail"],
            "upgrades": graded_outcome["upgrade_detail"],
            "effect": outcome.get("effect"),
        })

    body_start, body_warns, _, body_model = _body_start_certainty(
        (dossier or {}).get("design") or "body-of-evidence",
        (dossier or {}).get("underlying_design"),
        studies,
    )
    warnings.extend(body_warns)
    profile = {
        "schema": "bio-audit/grade-evidence-dossier/1",
        "method_basis": {
            "certainty_domains": _DOWNGRADE_DOMAINS + _UPGRADE_DOMAINS,
            "risk_of_bias_template": "RoB 2-style domains for randomized trials; accepts ROBINS/custom overall judgments too",
            "presentation": "GRADE evidence profile / Summary of Findings table",
        },
        "question": dossier.get("question") or dossier.get("pico") or "",
        "pico": dossier.get("pico") or {},
        "body_of_evidence": {
            "n_studies": len(studies),
            "starting_certainty": _LEVEL_NAME[body_start],
            "starting_certainty_model": body_model,
            "study_ids": [
                s.get("study_id") or s.get("id") or s.get("citation") or "<unknown>"
                for s in studies
            ],
        },
        "outcomes": outcome_profiles,
        "graded_outcomes": graded,
        "sof_markdown": grade_sof_table(graded_outcomes=graded, language=language),
        "warnings": warnings,
        "dossier_contract": {
            "required_top_level": ["question or pico", "studies", "outcomes"],
            "study_risk_of_bias": {
                "overall": "low|some_concerns|high|critical",
                "domains": _ROB2_DOMAINS,
                "reason": "support for judgement / reviewer note",
            },
            "outcome_domains": _DOWNGRADE_DOMAINS,
        },
    }
    return profile


@server.tool(
    "grade_sof_table",
    "Build a GRADE Summary of Findings (SoF) table (Markdown) from a list of graded outcomes "
    "(each = the output of grade_outcome). Columns: Outcome · № participants (studies) · Effect · "
    "Certainty (⊕) · Why (key downgrades). This is the artifact top-tier medical reviews put in front "
    "of clinicians — certainty per outcome, with the reason visible.",
    {
        "type": "object",
        "properties": {
            "graded_outcomes": {
                "type": "array",
                "description": "List of grade_outcome results.",
                "items": {"type": "object"},
            },
            "language": {"type": "string", "enum": ["zh", "en"], "default": "zh"},
        },
        "required": ["graded_outcomes"],
    },
)
def grade_sof_table(graded_outcomes: List[Dict[str, Any]], language: str = "zh"):
    if language == "zh":
        headers = ["Outcome（结局）", "参与者 (研究数)", "效应量", "证据确定性", "关键降级理由"]
    else:
        headers = ["Outcome", "№ participants (studies)", "Effect", "Certainty", "Key reasons"]
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for g in graded_outcomes:
        outcome = (g.get("outcome") or "").replace("|", "\\|")
        n_p = g.get("n_participants")
        n_s = g.get("n_studies")
        part = f"{n_p if n_p is not None else '—'} ({n_s if n_s is not None else '?'})"
        eff = g.get("effect") or {}
        if eff.get("measure"):
            ci = ""
            if eff.get("ci_low") is not None and eff.get("ci_high") is not None:
                ci = f" [{eff['ci_low']}, {eff['ci_high']}]"
            eff_s = f"{eff.get('measure')} {eff.get('value', '?')}{ci}"
        else:
            eff_s = "—"
        cert = f"{g.get('symbol', '')} {g.get('certainty', '?')}"
        key = "; ".join(d["domain_zh"] for d in (g.get("downgrade_detail") or [])
                        if d.get("points", 0) < 0) or "无降级"
        lines.append("| " + " | ".join([outcome, part, eff_s, cert, key]) + " |")
    # 脚注：确定性含义
    lines.append("")
    lines.append("> 证据确定性（GRADE）：⊕⊕⊕⊕ 高 · ⊕⊕⊕⊝ 中 · ⊕⊕⊝⊝ 低 · ⊕⊝⊝⊝ 极低。"
                 "确定性反映「我们对效应估计的把握」，不是效应大小。")
    return "\n".join(lines)


@server.tool(
    "grade_explain",
    "Return GRADE domain definitions (the 5 downgrade + 3 upgrade domains) and rating criteria — "
    "a transparency reference so the model and user align on what 'serious inconsistency' etc. mean.",
    {"type": "object", "properties": {}},
)
def grade_explain():
    return {
        "starting_certainty": {
            "RCT / systematic-review-of-rcts": "High (⊕⊕⊕⊕)",
            "非随机试验 / 单臂试验 / 观察性（cohort/case-control）": "Low (⊕⊕⊝⊝)",
            "病例系列 / 机制 / 动物 / 体外": "Very Low (⊕⊝⊝⊝)",
            "⚠ 'clinical-trial'（模糊）": "必须拆成 rct（High）或 single-arm/non-randomized（Low），不默认 High",
            "⚠ meta-analysis / systematic-review": "起始档取决于 underlying_design；未声明则保守按 Low，不默认 High",
        },
        "downgrade_domains": {
            "risk_of_bias（偏倚风险）": "研究层面的方法学缺陷：随机化/盲法/失访/选择性报告。serious=-1, very serious=-2",
            "inconsistency（不一致性）": "各研究结果方向/大小不一致，异质性大（I² 高、置信区间少重叠）",
            "indirectness（间接性）": "人群/干预/对照/结局与临床问题不完全吻合（含跨物种、替代终点）",
            "imprecision（不精确性）": "置信区间宽，或样本量/事件数不足，跨越临床决策阈值",
            "publication_bias（发表偏倚）": "小样本阳性结果被优先发表（漏斗图不对称、行业赞助）",
        },
        "upgrade_domains": {
            "large_effect（大效应量）": "RR<0.5 或 >2（+1）；RR<0.2 或 >5（+2）。仅观察性、无降级时用",
            "dose_response（剂量-反应）": "存在剂量-反应梯度（+1）",
            "plausible_confounding（残余混杂会削弱）": "所有可能的混杂只会削弱观察到的效应（+1）",
        },
        "rules": [
            "RCT 体系不可升级——升级只用于无严重局限的观察性证据。",
            "每一次降级/升级都必须给出「为什么」的具体理由，否则不透明。",
            "确定性是对'效应估计的把握'的评级，与效应大小、统计显著性是两回事。",
            "GRADE 评的是一个 outcome 的整体证据体，不是单篇文献。",
        ],
    }


# =====================================================================
# EtD：从证据确定性到推荐强度（Evidence to Decision）
# =====================================================================
# certainty 只回答"证据有多确定"。要不要**推荐**、推荐得**多强**（strong / conditional），
# 还得看 GRADE EtD 框架的其它维度：获益/危害平衡、价值观与偏好、资源/成本、公平性、
# 可接受性、可行性。工具把"从各维度判断到推荐方向+强度"的规则做成确定性映射，模型给判断。

_CERTAINTY_SCORE = {"high": 4, "moderate": 3, "low": 2, "very low": 1, "very_low": 1}
_BALANCE = {"favors_intervention", "favors_comparison", "balanced", "uncertain"}
_VALUES = {"no_important_variability", "important_variability", "uncertain"}
_RESOURCES = {"favors_intervention", "favors_comparison", "negligible", "uncertain"}
_IMPLEMENTATION = {"favors_intervention", "favors_comparison", "balanced", "uncertain"}


def _dist_from_value(obj: Any, allowed: set[str], default: str) -> Dict[str, float]:
    if isinstance(obj, dict) and isinstance(obj.get("probabilities"), dict):
        raw = obj["probabilities"]
    elif isinstance(obj, dict) and isinstance(obj.get("distribution"), dict):
        raw = obj["distribution"]
    elif isinstance(obj, dict) and any(
        (_normalise_rating(k) == "very_low" and "very low" in allowed) or _normalise_rating(k) in allowed
        for k in obj.keys()
    ):
        raw = obj
    elif isinstance(obj, dict):
        rating = _normalise_rating(obj.get("rating") or default)
        raw = {rating: 1.0}
    else:
        raw = {_normalise_rating(obj or default): 1.0}
    out: Dict[str, float] = {}
    for k, v in raw.items():
        key = _normalise_rating(k)
        if key == "very_low":
            key = "very low"
        if key in allowed:
            try:
                p = float(v)
            except (TypeError, ValueError):
                p = 0.0
            if p > 0:
                out[key] = out.get(key, 0.0) + p
    if not out:
        out[default] = 1.0
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in sorted(out.items())}


def _etd_state_decision(certainty: str, balance: str, values: str, resources: str,
                        equity: str, acceptability: str, feasibility: str) -> Dict[str, Any]:
    c_score = _CERTAINTY_SCORE.get(_normalise_rating(certainty), 1)
    if balance == "favors_intervention":
        direction = "for"
    elif balance == "favors_comparison":
        direction = "against"
    else:
        direction = "no_clear_direction"
    implementation_ok = all(
        x not in {"favors_comparison", "uncertain"}
        for x in (equity, acceptability, feasibility)
    )
    resource_conflicts = (
        (direction == "for" and resources == "favors_comparison")
        or (direction == "against" and resources == "favors_intervention")
    )
    strong = (
        c_score >= 3
        and direction in {"for", "against"}
        and values == "no_important_variability"
        and not resource_conflicts
        and implementation_ok
    )
    utility = {
        "favors_intervention": 1.0,
        "favors_comparison": -1.0,
        "balanced": 0.0,
        "uncertain": 0.0,
    }.get(balance, 0.0)
    utility *= c_score / 4.0
    if values == "important_variability":
        utility *= 0.7
    if resource_conflicts:
        utility *= 0.75
    if not implementation_ok:
        utility *= 0.75
    return {"direction": direction, "strength": "strong" if strong else "conditional", "utility": utility}


@server.tool(
    "etd_recommendation",
    "GRADE Evidence-to-Decision layer: turn certainty of evidence + judgments on benefit/harm balance, "
    "values & preferences, resources/cost (and optionally equity/acceptability/feasibility) into a "
    "recommendation DIRECTION (for/against) and STRENGTH (strong/conditional). Deterministic mapping + "
    "GRADE guards: a STRONG recommendation on LOW/VERY-LOW certainty is flagged as a 'discordant' "
    "recommendation that must fit one of GRADE's paradigmatic exceptions or be downgraded to conditional. "
    "Certainty alone never implies a recommendation — this is the required next step after grade_outcome.",
    {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "PICO question the recommendation answers"},
            "certainty": {"type": "string", "enum": ["High", "Moderate", "Low", "Very Low"],
                          "description": "Overall certainty across critical outcomes (from grade_outcome)"},
            "benefit_harm_balance": {
                "type": "object",
                "description": "{rating: favors_intervention|favors_comparison|balanced|uncertain, reason}",
            },
            "values_preferences": {
                "type": "object",
                "description": "{rating: no_important_variability|important_variability|uncertain, reason}",
            },
            "resources": {
                "type": "object",
                "description": "{rating: favors_intervention|favors_comparison|negligible|uncertain, reason}",
            },
            "equity": {"type": "object", "description": "optional {rating, reason}"},
            "acceptability": {"type": "object", "description": "optional {rating, reason}"},
            "feasibility": {"type": "object", "description": "optional {rating, reason}"},
        },
        "required": ["certainty", "benefit_harm_balance"],
    },
)
def etd_recommendation(certainty: str, benefit_harm_balance: Dict[str, Any],
                       question: str = "",
                       values_preferences: Optional[Dict[str, Any]] = None,
                       resources: Optional[Dict[str, Any]] = None,
                       equity: Optional[Dict[str, Any]] = None,
                       acceptability: Optional[Dict[str, Any]] = None,
                       feasibility: Optional[Dict[str, Any]] = None):
    warnings: List[str] = []
    c_score = _CERTAINTY_SCORE.get((certainty or "").strip().lower(), 1)
    balance = (benefit_harm_balance or {}).get("rating", "uncertain")
    values = (values_preferences or {}).get("rating", "uncertain")
    res = (resources or {}).get("rating", "uncertain")

    # 方向
    if balance == "favors_intervention":
        direction = "for"
    elif balance == "favors_comparison":
        direction = "against"
    else:
        direction = "either / no clear direction"

    # 强度：strong 需 ≥Moderate 确定性 + 明确净获益 + 价值观无重要变异 + 资源不反对
    strong_ok = (
        c_score >= 3
        and balance in ("favors_intervention", "favors_comparison")
        and values == "no_important_variability"
        and res != "favors_comparison"
    )
    strength = "strong" if strong_ok else "conditional"

    # GRADE 守卫：低确定性上的强推荐属"不一致推荐"
    if strength == "strong" and c_score <= 2:
        warnings.append("低/极低确定性证据上给强推荐属 GRADE『不一致(discordant)推荐』，"
                        "仅在 5 类特殊情形成立（如低确定性但获益巨大/危害极小、生命威胁、"
                        "等价选项中成本悬殊等）——必须显式说明属哪一类，否则应降为 conditional")
    if direction.startswith("either") and strength == "strong":
        strength = "conditional"
        warnings.append("获益/危害平衡不明确 → 无法给强推荐，已降为 conditional")
    if values == "important_variability" and strength == "strong":
        strength = "conditional"
        warnings.append("患者价值观/偏好存在重要变异 → GRADE 倾向 conditional（应支持共同决策）")
    for name, obj in [("resources", resources), ("values_preferences", values_preferences)]:
        if obj and obj.get("rating") and not obj.get("reason"):
            warnings.append(f"{name} 给了判断但没写理由——EtD 每个维度都要可核对")

    # 措辞（GRADE 惯例：strong='recommend'，conditional='suggest'）
    verb = "recommend" if strength == "strong" else "suggest"
    zh_strength = "强推荐" if strength == "strong" else "有条件推荐（弱推荐）"
    if direction == "for":
        statement = f"We {verb} using the intervention.（{zh_strength}使用）"
    elif direction == "against":
        statement = f"We {verb} against the intervention.（{zh_strength}不使用）"
    else:
        statement = f"证据不足以给出明确方向；建议个体化 / 共同决策（{zh_strength}框架下）。"

    rationale = [
        f"证据确定性：{certainty}",
        f"获益/危害平衡：{balance}（{(benefit_harm_balance or {}).get('reason') or '未说明'}）",
        f"价值观与偏好：{values}（{(values_preferences or {}).get('reason') or '未说明'}）",
        f"资源/成本：{res}（{(resources or {}).get('reason') or '未说明'}）",
    ]
    for label, obj in [("公平性", equity), ("可接受性", acceptability), ("可行性", feasibility)]:
        if obj and obj.get("rating"):
            rationale.append(f"{label}：{obj.get('rating')}（{obj.get('reason') or '未说明'}）")

    return {
        "question": question,
        "direction": direction,
        "strength": strength,
        "strength_zh": zh_strength,
        "statement": statement,
        "rationale": rationale,
        "warnings": warnings,
        "note": "certainty 只是 EtD 的一个维度；推荐强度由全部维度共同决定。"
                "strong→'recommend'，conditional→'suggest'（GRADE 措辞惯例）。",
    }


@server.tool(
    "etd_probabilistic_recommendation",
    "Probabilistic GRADE Evidence-to-Decision. Accepts probability distributions for certainty, "
    "benefit/harm balance, values, resources, equity, acceptability and feasibility, enumerates the "
    "joint state space, and returns posterior probabilities for direction and strength. Use this when "
    "panel judgments are uncertain or split instead of forcing a deterministic if-else recommendation.",
    {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "certainty": {"type": "object", "description": "{probabilities:{High:0.4, Moderate:0.6}} or {rating:'High'}"},
            "benefit_harm_balance": {"type": "object", "description": "{probabilities:{favors_intervention:0.7, balanced:0.3}} or {rating, reason}"},
            "values_preferences": {"type": "object"},
            "resources": {"type": "object"},
            "equity": {"type": "object"},
            "acceptability": {"type": "object"},
            "feasibility": {"type": "object"},
            "strong_threshold": {"type": "number", "default": 0.75},
            "direction_threshold": {"type": "number", "default": 0.7},
        },
        "required": ["certainty", "benefit_harm_balance"],
    },
)
def etd_probabilistic_recommendation(
    certainty: Dict[str, Any],
    benefit_harm_balance: Dict[str, Any],
    question: str = "",
    values_preferences: Optional[Dict[str, Any]] = None,
    resources: Optional[Dict[str, Any]] = None,
    equity: Optional[Dict[str, Any]] = None,
    acceptability: Optional[Dict[str, Any]] = None,
    feasibility: Optional[Dict[str, Any]] = None,
    strong_threshold: float = 0.75,
    direction_threshold: float = 0.7,
):
    cert_d = _dist_from_value(certainty, {"high", "moderate", "low", "very low"}, "low")
    bal_d = _dist_from_value(benefit_harm_balance, _BALANCE, "uncertain")
    val_d = _dist_from_value(values_preferences or {"rating": "uncertain"}, _VALUES, "uncertain")
    res_d = _dist_from_value(resources or {"rating": "uncertain"}, _RESOURCES, "uncertain")
    eq_d = _dist_from_value(equity or {"rating": "balanced"}, _IMPLEMENTATION, "balanced")
    acc_d = _dist_from_value(acceptability or {"rating": "balanced"}, _IMPLEMENTATION, "balanced")
    feas_d = _dist_from_value(feasibility or {"rating": "balanced"}, _IMPLEMENTATION, "balanced")

    posterior = {
        "direction": {"for": 0.0, "against": 0.0, "no_clear_direction": 0.0},
        "strength": {"strong": 0.0, "conditional": 0.0},
    }
    expected_utility = 0.0
    top_states: List[Dict[str, Any]] = []
    for c, cp in cert_d.items():
        for b, bp in bal_d.items():
            for v, vp in val_d.items():
                for r, rp in res_d.items():
                    for e, ep in eq_d.items():
                        for a, ap in acc_d.items():
                            for f, fp in feas_d.items():
                                p = cp * bp * vp * rp * ep * ap * fp
                                decision = _etd_state_decision(c, b, v, r, e, a, f)
                                posterior["direction"][decision["direction"]] += p
                                posterior["strength"][decision["strength"]] += p
                                expected_utility += p * decision["utility"]
                                top_states.append({
                                    "probability": p,
                                    "certainty": c,
                                    "benefit_harm_balance": b,
                                    "values_preferences": v,
                                    "resources": r,
                                    "equity": e,
                                    "acceptability": a,
                                    "feasibility": f,
                                    "direction": decision["direction"],
                                    "strength": decision["strength"],
                                })
    top_states.sort(key=lambda x: x["probability"], reverse=True)
    best_direction, p_direction = max(posterior["direction"].items(), key=lambda kv: kv[1])
    p_strong = posterior["strength"]["strong"]
    strength = "strong" if p_strong >= strong_threshold and p_direction >= direction_threshold else "conditional"
    if best_direction == "no_clear_direction" or p_direction < direction_threshold:
        statement = "Evidence-to-decision judgments remain uncertain; use shared decision-making and do not issue a directional recommendation."
    else:
        verb = "recommend" if strength == "strong" else "suggest"
        statement = (
            f"We {verb} using the intervention."
            if best_direction == "for"
            else f"We {verb} against the intervention."
        )
    warnings = []
    if posterior["direction"]["no_clear_direction"] >= 0.25:
        warnings.append("≥25% posterior mass has no clear direction; panel discussion should focus on benefit/harm uncertainty.")
    if posterior["strength"]["strong"] > 0 and strength != "strong":
        warnings.append("Some states support a strong recommendation, but posterior confidence does not pass thresholds.")
    return {
        "question": question,
        "posterior": {
            "direction": {k: round(v, 4) for k, v in posterior["direction"].items()},
            "strength": {k: round(v, 4) for k, v in posterior["strength"].items()},
        },
        "expected_utility": round(expected_utility, 4),
        "direction": best_direction,
        "strength": strength,
        "statement": statement,
        "thresholds": {
            "strong_threshold": strong_threshold,
            "direction_threshold": direction_threshold,
        },
        "input_distributions": {
            "certainty": cert_d,
            "benefit_harm_balance": bal_d,
            "values_preferences": val_d,
            "resources": res_d,
            "equity": eq_d,
            "acceptability": acc_d,
            "feasibility": feas_d,
        },
        "top_joint_states": top_states[:8],
        "warnings": warnings,
    }


if __name__ == "__main__":
    server.run()
