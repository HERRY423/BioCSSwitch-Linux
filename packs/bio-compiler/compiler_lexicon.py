"""研究问题编译器的词表与路由表 —— 确定性、可核对、可解释。

分成三块：
  1. 实体识别：疾病缩写表、常见靶点基因集、药物后缀/已知药名 → 从模糊问题里挖出结构化实体。
  2. 问题原型（archetype）识别：靶点验证 / 老药新用 / 生物标志物 / 机制 / 疗效比较 /
     流行病学 / 安全性 —— 决定终点、数据库、工具链、该进哪个 workflow skill。
  3. 路由表：每个原型 → 推荐数据库 / 工具链 / 证据等级门槛 / workflow skill。

**刻意不做的事**：不接大模型、不做黑盒 NER。识别不到就标 unknown，交给 skill 追问用户。
这样编译结果永远可核对——每个字段都能指到"凭哪条规则得到"。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 1. 疾病缩写 → 规范名（+ 本体提示）。只收高频、歧义小的。
# ---------------------------------------------------------------------------
DISEASE_ABBR: Dict[str, Dict[str, str]] = {
    "GBM": {"name": "Glioblastoma", "ontology_hint": "MONDO:0018177", "area": "oncology"},
    "NSCLC": {"name": "Non-small cell lung cancer", "ontology_hint": "EFO:0003060", "area": "oncology"},
    "SCLC": {"name": "Small cell lung cancer", "ontology_hint": "EFO:0000702", "area": "oncology"},
    "TNBC": {"name": "Triple-negative breast cancer", "ontology_hint": "MONDO:0005494", "area": "oncology"},
    "HCC": {"name": "Hepatocellular carcinoma", "ontology_hint": "EFO:0000182", "area": "oncology"},
    "CRC": {"name": "Colorectal cancer", "ontology_hint": "EFO:0005842", "area": "oncology"},
    "AML": {"name": "Acute myeloid leukemia", "ontology_hint": "EFO:0000222", "area": "oncology"},
    "CLL": {"name": "Chronic lymphocytic leukemia", "ontology_hint": "EFO:0000095", "area": "oncology"},
    "PDAC": {"name": "Pancreatic ductal adenocarcinoma", "ontology_hint": "MONDO:0006047", "area": "oncology"},
    "RCC": {"name": "Renal cell carcinoma", "ontology_hint": "EFO:0000681", "area": "oncology"},
    "AD": {"name": "Alzheimer disease", "ontology_hint": "MONDO:0004975", "area": "neurology"},
    "PD": {"name": "Parkinson disease", "ontology_hint": "MONDO:0005180", "area": "neurology"},
    "ALS": {"name": "Amyotrophic lateral sclerosis", "ontology_hint": "MONDO:0004976", "area": "neurology"},
    "MS": {"name": "Multiple sclerosis", "ontology_hint": "MONDO:0005301", "area": "neurology"},
    "RA": {"name": "Rheumatoid arthritis", "ontology_hint": "EFO:0000685", "area": "immunology"},
    "SLE": {"name": "Systemic lupus erythematosus", "ontology_hint": "EFO:0002690", "area": "immunology"},
    "IBD": {"name": "Inflammatory bowel disease", "ontology_hint": "EFO:0003767", "area": "immunology"},
    "UC": {"name": "Ulcerative colitis", "ontology_hint": "EFO:0000729", "area": "immunology"},
    "T2D": {"name": "Type 2 diabetes mellitus", "ontology_hint": "MONDO:0005148", "area": "metabolic"},
    "T2DM": {"name": "Type 2 diabetes mellitus", "ontology_hint": "MONDO:0005148", "area": "metabolic"},
    "NASH": {"name": "Non-alcoholic steatohepatitis", "ontology_hint": "EFO:1001249", "area": "metabolic"},
    "COPD": {"name": "Chronic obstructive pulmonary disease", "ontology_hint": "EFO:0000341", "area": "respiratory"},
    "CKD": {"name": "Chronic kidney disease", "ontology_hint": "EFO:0003884", "area": "nephrology"},
    "HFpEF": {"name": "Heart failure with preserved ejection fraction", "ontology_hint": "EFO:0009887", "area": "cardiology"},
}

# 中文疾病别名（口语 → 规范英文），只收最常踩的。
DISEASE_ZH: Dict[str, str] = {
    "胶质母细胞瘤": "Glioblastoma", "非小细胞肺癌": "Non-small cell lung cancer",
    "三阴乳腺癌": "Triple-negative breast cancer", "肝细胞癌": "Hepatocellular carcinoma",
    "结直肠癌": "Colorectal cancer", "胰腺癌": "Pancreatic ductal adenocarcinoma",
    "阿尔茨海默": "Alzheimer disease", "帕金森": "Parkinson disease",
    "类风湿": "Rheumatoid arthritis", "红斑狼疮": "Systemic lupus erythematosus",
    "炎症性肠病": "Inflammatory bowel disease", "2型糖尿病": "Type 2 diabetes mellitus",
    "乳腺癌": "Breast cancer", "肺癌": "Lung cancer", "肝癌": "Liver cancer",
    "胃癌": "Gastric cancer", "白血病": "Leukemia", "黑色素瘤": "Melanoma",
}

# ---------------------------------------------------------------------------
# 2. 常见靶点基因（用于给"看起来像基因的 token"加可信度；不是穷举，是加权用）。
# ---------------------------------------------------------------------------
KNOWN_TARGETS = {
    "EGFR", "KRAS", "TP53", "BRAF", "ALK", "MET", "HER2", "ERBB2", "PIK3CA",
    "PTEN", "MYC", "BCL2", "CDK4", "CDK6", "MDM2", "IDH1", "IDH2", "FGFR1",
    "FGFR2", "FGFR3", "VEGFA", "VEGFR2", "KDR", "PDGFRA", "KIT", "RET", "ROS1",
    "NTRK1", "BRCA1", "BRCA2", "PARP1", "MTOR", "AKT1", "STK11", "KEAP1",
    "NF1", "RB1", "SMAD4", "APC", "CTNNB1", "JAK2", "STAT3", "IL6", "TNF",
    "PD1", "PDCD1", "CD274", "CTLA4", "LAG3", "TIGIT", "CD19", "BCMA", "GPC3",
    "SOD1", "APP", "MAPT", "SNCA", "LRRK2", "HTT", "GBA", "TREM2",
}

# 基因符号形状：2-6 位大写字母/数字，首字母字母。排除纯常见英文缩写。
_GENE_SHAPE = re.compile(r"\b([A-Z][A-Z0-9]{1,5}[0-9]?)\b")
# 明显不是基因的大写缩写黑名单（否则 RCT / DNA / RNA / FDA 会被误判）。
_GENE_STOP = {"RCT", "DNA", "RNA", "FDA", "USA", "PICO", "PECO", "OS", "PFS", "ORR",
              "DFS", "HR", "OR", "RR", "CI", "AI", "ML", "II", "III", "IV", "PDF",
              "JSON", "MCP", "API", "GEO", "SRA", "PMID", "DOI", "NCT", "MRI", "CT",
              "PET", "ECG", "BMI", "QOL", "AE", "SAE", "IC50", "EC50", "KI"}

# ---------------------------------------------------------------------------
# 3. 药物识别：后缀 + 已知药名（小样本）。
# ---------------------------------------------------------------------------
DRUG_SUFFIX = ("mab", "nib", "tinib", "ciclib", "lisib", "parib", "degib",
               "vastatin", "statin", "gliptin", "gliflozin", "sartan", "prazole",
               "zumab", "ximab", "umab", "limus")
KNOWN_DRUGS = {
    "metformin", "aspirin", "pembrolizumab", "nivolumab", "sotorasib", "adagrasib",
    "osimertinib", "gefitinib", "erlotinib", "imatinib", "trastuzumab", "bevacizumab",
    "olaparib", "palbociclib", "semaglutide", "empagliflozin",
    "dapagliflozin", "atorvastatin", "rituximab", "cetuximab", "temozolomide",
    "thalidomide", "sildenafil",
}

# 中文药名别名（口语 → 规范英文），只收最常见的。
DRUG_ZH: Dict[str, str] = {
    "二甲双胍": "metformin", "阿司匹林": "aspirin", "沙利度胺": "thalidomide",
    "西地那非": "sildenafil", "伊马替尼": "imatinib", "曲妥珠单抗": "trastuzumab",
    "贝伐珠单抗": "bevacizumab", "利妥昔单抗": "rituximab", "替莫唑胺": "temozolomide",
    "奥希替尼": "osimertinib", "吉非替尼": "gefitinib",
}


# ---------------------------------------------------------------------------
# 问题原型（archetype）识别规则：关键词命中 → 原型。
# ---------------------------------------------------------------------------
ARCHETYPES: List[Tuple[str, List[str]]] = [
    ("target-validation",
     ["靶点价值", "新靶点", "还有没有.*价值", "target value", "druggable", "靶点发现",
      "target identification", "target discovery", "值得做靶点", "成药性", "值不值得打"]),
    ("drug-repurposing",
     ["老药新用", "重定位", "repurpos", "repositioning", "新适应症", "还能治",
      "还能用", "off-label", "现有药.*用于", "换个适应症"]),
    ("biomarker",
     ["biomarker", "生物标志物", "标志物", "预测.*疗效", "预后", "prognostic",
      "predictive", "分层", "stratif", "companion diagnostic", "伴随诊断"]),
    ("mechanism",
     ["机制", "mechanism", "pathway", "通路", "如何调控", "signaling", "moa",
      "作用机制", "为什么.*导致"]),
    ("efficacy-comparison",
     ["疗效", "有效性", "efficacy", "谁更好", "优于", "比较", "vs\\b", "head to head",
      "哪个更", "孰优", "非劣", "superiority", "non-inferior"]),
    ("epidemiology",
     ["发病率", "患病率", "流行病学", "incidence", "prevalence", "epidemiolog",
      "多少人", "risk factor", "危险因素"]),
    ("safety",
     ["安全性", "副作用", "不良反应", "毒性", "safety", "adverse", "toxicity",
      "禁忌", "drug interaction", "药物相互作用", "ddi"]),
]

# 每个原型 → 路由信息。
ROUTES: Dict[str, Dict[str, Any]] = {
    "target-validation": {
        "endpoints": ["遗传学关联（GWAS / OMIM / clinical genetics）",
                      "功能依赖性（CRISPR 依赖 / DepMap）",
                      "成药性（结构类别 / 已有活性化合物 / 抗体可及）",
                      "临床先例（是否已有在研药物 / 试验结局）"],
        "databases": ["Open Targets", "PubMed", "ClinicalTrials.gov", "ChEMBL", "UniProt", "HGNC"],
        "toolchain": [
            ("disambiguate", "把基因/疾病口语名归一到 HGNC / MONDO"),
            ("ot_disease_associated_targets", "拉疾病相关靶点，按综合分排序"),
            ("ot_target_associated_diseases", "反向看该靶点还关联哪些病"),
            ("chembl_target_search", "看靶点是否有活性化合物（成药性信号）"),
            ("ctgov_search", "查是否已有针对该靶点的临床试验（临床先例）"),
            ("evidence_graph", "对关键关联做 claim 级证据审计（警惕 text-mining 弱证据）"),
            ("uncertainty_ledger", "暴露 known unknowns / 冲突 / 缺失数据"),
        ],
        "evidence_bar": "结论级需 ≥ 功能基因组学 + 临床关联双线证据；仅 text-mining co-mention 不足以下'有价值'结论。",
        "skill": "target-discovery",
    },
    "drug-repurposing": {
        "endpoints": ["靶点重叠", "共享通路", "已有临床证据（试验存在与否/结果）",
                      "安全性/DDI 是否卡住新适应症"],
        "databases": ["ChEMBL", "Open Targets", "RxNorm", "openFDA", "ClinicalTrials.gov", "PubMed"],
        "toolchain": [
            ("chembl_compound_search", "拿化合物 ChEMBL ID"),
            ("chembl_mechanism", "主要靶点 + action_type"),
            ("ot_target_associated_diseases", "靶点相邻疾病 = 重定位候选"),
            ("ctgov_search", "该药×候选疾病是否已被试过（失败/在跑/没人做）"),
            ("fda_label", "现有标签的警告 / 禁忌 / DDI"),
            ("evidence_graph", "候选证据审计"),
            ("uncertainty_ledger", "盲区/冲突面板"),
        ],
        "evidence_bar": "新适应症候选需 ≥ 机制合理性 + 无致命安全阻断；有阴性临床试验的候选要显式标注。",
        "skill": "target-discovery",
    },
    "biomarker": {
        "endpoints": ["预测性（predict response）", "预后性（prognosis）", "AUC / HR / 敏感度特异度",
                      "是否有前瞻验证"],
        "databases": ["PubMed", "Open Targets", "GEO", "ClinicalTrials.gov"],
        "toolchain": [
            ("disambiguate", "标志物 / 疾病归一"),
            ("pubmed_search", "检索标志物-结局关联文献"),
            ("geo_search", "找可复现的组学数据集"),
            ("evidence_graph", "区分'回顾性发现'与'前瞻验证'"),
            ("uncertainty_ledger", "盲区/冲突面板"),
        ],
        "evidence_bar": "临床可用需 ≥ 独立队列前瞻验证；单中心回顾性发现只能算'候选'。",
        "skill": "lit-review",
    },
    "mechanism": {
        "endpoints": ["通路归属", "上下游调控", "功能实验证据（敲除/过表达）", "物种边界"],
        "databases": ["PubMed", "UniProt", "Open Targets", "Reactome（经 OLS/GO）"],
        "toolchain": [
            ("disambiguate", "分子/通路归一"),
            ("uniprot_entry", "功能 / 定位 / 通路注释"),
            ("pubmed_search", "机制文献"),
            ("evidence_graph", "把机制 claim 绑到具体实验证据 + 物种边界"),
            ("uncertainty_ledger", "盲区/冲突面板"),
        ],
        "evidence_bar": "机制结论要标清是体外 / 动物 / 人类；跨物种外推必须显式声明。",
        "skill": "target-discovery",
    },
    "efficacy-comparison": {
        "endpoints": ["OS", "PFS", "ORR", "DFS", "安全性终点", "生活质量"],
        "databases": ["PubMed", "ClinicalTrials.gov", "Cochrane（经 EPMC）"],
        "toolchain": [
            ("pubmed_search", "拉 head-to-head / meta-analysis"),
            ("ctgov_search", "对应注册试验的终点/样本量/状态"),
            ("analyze_endpoints", "系统比较终点定义"),
            ("evidence_graph", "每条疗效结论绑证据等级 + 适用边界"),
            ("uncertainty_ledger", "盲区/冲突面板"),
        ],
        "evidence_bar": "'A 优于 B'需 ≥ RCT 或 meta-analysis；不同终点/人群的间接比较要显式标注为间接证据。",
        "skill": "lit-review",
    },
    "epidemiology": {
        "endpoints": ["发病率", "患病率", "相对风险 / 风险比", "人群/地域分层"],
        "databases": ["PubMed", "（外部：GBD / WHO / 各国登记，本地不覆盖）"],
        "toolchain": [
            ("pubmed_search", "检索人群研究 / 登记数据"),
            ("evidence_graph", "区分单中心 vs 全国登记；标清年份/地域"),
            ("uncertainty_ledger", "盲区/冲突面板"),
        ],
        "evidence_bar": "流行病学数字要标明人群/年份/地域；不可把某国数据直接外推到全球。",
        "skill": "lit-review",
    },
    "safety": {
        "endpoints": ["常见/严重不良反应", "黑框警告", "DDI", "特殊人群禁忌"],
        "databases": ["openFDA", "RxNorm", "ClinicalTrials.gov", "PubMed"],
        "toolchain": [
            ("fda_label", "标签警告 / 禁忌 / DDI"),
            ("pubmed_search", "上市后安全性文献 / 药物警戒"),
            ("evidence_graph", "把安全性 claim 绑到具体来源"),
            ("uncertainty_ledger", "盲区/冲突面板"),
        ],
        "evidence_bar": "安全性结论优先信监管标签 + 前瞻药物警戒；病例报告只能提示信号，不能定量。",
        "skill": "lit-review",
    },
    "unknown": {
        "endpoints": [],
        "databases": ["PubMed"],
        "toolchain": [("pubmed_search", "先做一次探索性检索，再回来重新编译问题")],
        "evidence_bar": "问题原型未识别 —— 先追问用户，别急着答。",
        "skill": "lit-review",
    },
}


def detect_diseases(q: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    # 缩写（大小写敏感，避免误伤）
    for abbr, info in DISEASE_ABBR.items():
        if re.search(rf"\b{re.escape(abbr)}\b", q):
            if info["name"] not in seen:
                out.append({"raw": abbr, "name": info["name"],
                            "ontology_hint": info["ontology_hint"],
                            "area": info["area"], "via": f"abbr:{abbr}"})
                seen.add(info["name"])
    # 中文别名
    for zh, name in DISEASE_ZH.items():
        if zh in q and name not in seen:
            out.append({"raw": zh, "name": name, "ontology_hint": None,
                        "area": None, "via": f"zh:{zh}"})
            seen.add(name)
    return out


def detect_genes(q: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for m in _GENE_SHAPE.finditer(q):
        tok = m.group(1)
        if tok in _GENE_STOP or tok in seen:
            continue
        # 已知靶点 → 高可信；否则形状匹配 → 低可信（标 candidate）
        if tok in KNOWN_TARGETS:
            out.append({"symbol": tok, "confidence": "high", "via": "known-target"})
            seen.add(tok)
        elif len(tok) >= 3 and any(ch.isdigit() for ch in tok) or tok in KNOWN_TARGETS:
            out.append({"symbol": tok, "confidence": "candidate", "via": "gene-shape"})
            seen.add(tok)
    return out


def detect_drugs(q: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    ql = q.lower()
    for zh, name in DRUG_ZH.items():
        if zh in q and name not in seen:
            out.append({"name": name, "confidence": "high", "via": f"zh:{zh}"})
            seen.add(name)
    for d in KNOWN_DRUGS:
        if re.search(rf"\b{re.escape(d)}\b", ql) and d not in seen:
            out.append({"name": d, "confidence": "high", "via": "known-drug"})
            seen.add(d)
    for m in re.finditer(r"\b([a-z]{4,}(?:" + "|".join(DRUG_SUFFIX) + r"))\b", ql):
        tok = m.group(1)
        if tok not in seen:
            out.append({"name": tok, "confidence": "candidate", "via": "drug-suffix"})
            seen.add(tok)
    return out


def detect_archetype(q: str) -> Tuple[str, List[str]]:
    """返回 (archetype, 命中的关键词)。多命中取第一个匹配的原型（ARCHETYPES 顺序即优先级）。"""
    ql = q.lower()
    for arch, patterns in ARCHETYPES:
        hits = [p for p in patterns if re.search(p.lower(), ql)]
        if hits:
            return arch, hits
    return "unknown", []
