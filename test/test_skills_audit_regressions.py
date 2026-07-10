from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location("audit_regression_" + rel.replace("/", "_"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_uncertainty_ledger_renders_english_panel():
    audit = load_module("packs/bio-audit/evidence_verify_server.py")
    result = audit.uncertainty_ledger(
        language="en",
        question="Does X improve survival?",
        graph_claims=[
            {
                "claim": "X improves survival in adults",
                "verdict": "supported",
                "evidence_level": "RCT",
                "applicability_boundary": {
                    "species_note": "human evidence",
                    "disease_stage": ["advanced"],
                    "max_sample_size": 220,
                },
                "conflicts": ["存在反证：1 条引用与结论方向相反"],
                "counter_evidence": [],
            },
            {
                "claim": "X is curative",
                "verdict": "unsupported",
                "evidence_level": "no valid evidence",
                "conflicts": [],
                "counter_evidence": [],
            },
        ],
    )

    assert result["markdown"].startswith("## Uncertainty Panel")
    assert "Research question: Does X improve survival?" in result["markdown"]
    assert "evidence level: RCT" in result["ledger"]["known_knowns"][0]
    assert "no valid citation" in result["ledger"]["known_unknowns"][0]
    assert "Counter-evidence exists: 1 citation(s)" in result["markdown"]
    assert "研究问题" not in result["markdown"]
    assert "证据等级" not in result["markdown"]
    assert "存在反证" not in result["markdown"]


def test_uncertainty_ledger_keeps_chinese_rendering_by_default():
    audit = load_module("packs/bio-audit/evidence_verify_server.py")
    result = audit.uncertainty_ledger(
        question="X 是否改善生存？",
        graph_claims=[
            {
                "claim": "X 改善生存",
                "verdict": "unsupported",
                "evidence_level": "无有效证据",
            }
        ],
    )
    assert result["markdown"].startswith("## 不确定性面板（Uncertainty Panel）")
    assert "> 研究问题：X 是否改善生存？" in result["markdown"]
    assert "无有效引用支持，尚不能确证" in result["markdown"]


def test_uncertainty_ledger_does_not_mislabel_mixed_species_as_preclinical_only():
    audit = load_module("packs/bio-audit/evidence_verify_server.py")
    result = audit.uncertainty_ledger(
        language="en",
        graph_claims=[
            {
                "claim": "X changes biomarker Y",
                "verdict": "supported",
                "evidence_level": "cohort",
                "applicability_boundary": {
                    "species_note": "人类 + 临床前混合证据",
                    "disease_stage": ["advanced"],
                    "max_sample_size": 80,
                },
            }
        ],
    )
    assert "mixed human and preclinical evidence" in result["markdown"]
    assert "lacks direct human evidence" not in result["markdown"]
    assert "Design a human validation study" not in result["markdown"]


def test_ctgov_analyze_endpoints_aggregates_without_detail_calls(monkeypatch):
    trials = load_module("packs/bio-trials/clinicaltrials_server.py")

    def fake_get_json(url, params):
        assert url.endswith("/studies")
        assert params["query.cond"] == "glioblastoma"
        return {
            "totalCount": 2,
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT00000001"},
                        "outcomesModule": {
                            "primaryOutcomes": [{"measure": "Overall Survival"}],
                            "secondaryOutcomes": [{"measure": "Progression-Free Survival"}],
                        },
                    }
                },
                {
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT00000002"},
                        "outcomesModule": {
                            "primaryOutcomes": [{"measure": "Overall Survival"}],
                            "secondaryOutcomes": [{"measure": "Objective Response Rate"}],
                        },
                    }
                },
            ],
        }

    monkeypatch.setattr(trials.http, "get_json", fake_get_json)
    result = trials.ctgov_analyze_endpoints(condition="glioblastoma", phase="PHASE2")

    assert "ctgov_analyze_endpoints" in trials.server.tools
    assert result["n_trials_scanned"] == 2
    assert result["primary"][0] == {
        "endpoint": "Overall Survival",
        "count": 2,
        "nct_ids": ["NCT00000001", "NCT00000002"],
    }
    assert {row["endpoint"] for row in result["secondary"]} == {
        "Progression-Free Survival",
        "Objective Response Rate",
    }


def test_audit_log_write_redacts_summary_and_extra_phi(tmp_path, monkeypatch):
    monkeypatch.setenv("CSSWITCH_AUDIT_DIR", str(tmp_path))
    audit_log = load_module("packs/bio-privacy/audit_server.py")

    result = audit_log.audit_log_write(
        event="redaction_applied",
        summary="Discussed Dr. John Doe and john.doe@example.com",
        input_sample="raw text is hashed only",
        extra={"note": "MRN: AB12345 should never be stored"},
    )

    entry = result["entry"]
    serialized = json.dumps(entry, ensure_ascii=False)
    assert "john.doe@example.com" not in serialized
    assert "AB12345" not in serialized
    assert "[REDACTED_" in serialized
    assert entry["privacy_warnings"]
    assert entry["input_digest_sha256_16"]


def test_bio_workflows_declares_tools_it_teaches():
    data = json.loads((ROOT / "packs/bio-workflows/pack.json").read_text(encoding="utf-8"))
    deps = set(data["dependencies"])
    assert {"bio-norm", "bio-drug", "bio-gene", "bio-trials"} <= deps
    assert data["dependencies"] == data["depends_on"]


def test_orphan_tools_are_called_from_their_skill_workflow_steps():
    critique = (ROOT / "packs/bio-critique/skills/scientific-critique/SKILL.md").read_text(encoding="utf-8")
    critique_workflow = critique.split("## Workflow", 1)[1].split("## Non-Negotiables", 1)[0]
    assert "`critique_checklist`" in critique_workflow
    assert "`design_counter_experiment`" in critique_workflow

    grade = (ROOT / "packs/bio-audit/skills/grade-sof/SKILL.md").read_text(encoding="utf-8")
    grade_workflow = grade.split("## 工作流", 1)[1].split("## 起始档的坑", 1)[0]
    assert "`grade_evidence_dossier`" in grade_workflow
    assert "`etd_probabilistic_recommendation`" in grade_workflow

    single_cell = (ROOT / "packs/bio-singlecell/skills/single-cell-prep/SKILL.md").read_text(encoding="utf-8")
    single_cell_workflow = single_cell.split("## 工作流", 1)[1].split("## 反例", 1)[0]
    assert "`sc_workflow_recipe`" in single_cell_workflow
