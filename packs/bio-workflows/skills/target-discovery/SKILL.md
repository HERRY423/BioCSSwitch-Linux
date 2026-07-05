---
name: target-discovery
description: 用于靶点发现 / 药物重定位 / drug repurposing / target identification / target prioritization / MoA hypothesis 场景。触发：帮我找靶点、target discovery、drug repurposing、老药新用、这个疾病有什么潜在靶点、这个化合物还能治什么、mechanism hypothesis、这个基因和 X 病有什么关系、靶点评分、靶点评级、target selection、pathway hypothesis、synthetic lethality candidate。禁用于：查单个靶点的基本信息——那用 hgnc_lookup_symbol / uniprot_entry 直接答就行。
---

# 靶点发现 / 药物重定位（target-discovery）

不给你"AI 建议这个靶点"，给你**证据链**：疾病 ↔ 靶点关联怎么来的、每一条证据强度如何、能不能被现有药物打。

## 触发后先明确一件事

用户要"从疾病找靶点"还是"从化合物找新适应症"？两条路走向不同。以下按这两条路分开写。

---

## 路径 A：从疾病 → 靶点

**Step 1：疾病规范化**。用户可能给的是"triple negative breast cancer"这种口语名。
- `ols_search` ontology=mondo 找 MONDO ID
- 拿到 EFO/MONDO ID 才能查 Open Targets

**Step 2：拉关联靶点**。
- `ot_disease_associated_targets` 用 EFO ID，size=50
- 按 Open Targets 综合分数排序
- 对 top-25 每个靶点：
  - `hgnc_lookup_symbol` 拿规范 symbol + 别名
  - `uniprot_entry` 拿功能 / 亚细胞定位 / 疾病关联段
  - `chembl_target_search` 看这个靶点在 ChEMBL 里有没有活性化合物

**Step 3：候选清单**。产出一张表：
`symbol | UniProt | subcellular | druggability_hint | OT_score | 已有活性化合物数 | 备注`

Druggability 提示的判断：G-protein coupled、kinase、hydrolase → 通常 druggable；transcription factor / scaffold → 通常不 druggable（但也可以 degrader）。

**Step 4：证据链**。对 top-3 的每个候选，走一遍 `evidence-audit`：把 Open Targets 归因的 PMID 逐条校验，警惕 "association driven by literature co-mention only" 这种弱证据（Open Targets 给的分数会包含 text-mining 权重）。

---

## 路径 B：从化合物 → 新适应症

**Step 1：化合物规范化**。
- `chembl_compound_search` 拿 ChEMBL ID
- `rxnorm_find_rxcui` 若是已上市药，拿 RxCUI

**Step 2：机制 + 靶点**。
- `chembl_mechanism` 拿主要靶点 + action_type
- `ot_drug_details` 拿 Open Targets 里已知适应症

**Step 3：靶点 → 相邻疾病**。对每个主靶点：
- `ot_target_associated_diseases` size=30
- 排除已知适应症（已在 `ot_drug_details.indications` 里的）
- 剩下的按分数排序 = **重定位候选**

**Step 4：可行性检查**。对 top-5 重定位候选疾病：
- `ctgov_search` intervention=<drug> condition=<disease> 看有没有已跑过的临床试验（有，说明有人试过 → 结果是失败？在跑？还是没人做过）
- `fda_label` 看该药现有标签里是否有相关警告 / DDI（如"孕妇禁用"卡掉 OB/GYN 适应症）

**Step 5：产出**。表格：
`候选适应症 | MONDO | 共享通路 | 已有临床证据 | 主要风险 | 优先级建议`

---

## 铁律

- **不下"推荐"结论**——你只提供证据链和优先级，最后由用户判断。这不是虚伪，是靶点发现的科学惯例：AI 说"推荐"很容易被断章取义当结论。
- **每张最终表都要能追溯**：Open Targets score 要给出来（别只讲"高"），临床试验要挂 NCT ID。
- **协同致死（synthetic lethality）等特殊场景**如果用户提，需要额外调 DepMap / Cellosaurus，这两个 CSSwitch 目前**没有**——明确告诉用户"目前只能给公开证据"。


## 收尾强制项：不确定性面板（uncertainty-first）

**本工作流的结论一律不得省略五段面板**：Known knowns / Known unknowns / Conflicts / Missing data / Next experiment。做法见 `uncertainty-first` skill —— 优先把结论拆成 claim 走 `evidence_graph`（每条 claim 自动绑证据等级 / 物种 / 样本量 / 疾病阶段 / 适用边界 / 反证），再把 `claims` 喂给 `uncertainty_ledger` 自动生成五段，补上工具挖不到的领域先验（`extra` 参数）后原样贴出。缺这五段，回答视为未完成——研究者要的正是被暴露的盲区。
