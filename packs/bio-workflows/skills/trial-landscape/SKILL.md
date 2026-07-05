---
name: trial-landscape
description: 用于临床试验管线 / 竞争情报 / landscape analysis / KOL 识别 / 试验设计 benchmark。触发：临床试验 landscape、pipeline analysis、compete intelligence、竞争管线、这个靶点有谁在做临床、这个适应症的三期试验有哪些、找 KOL、principal investigator、endpoint benchmark、试验设计参考、market landscape、我要写一份 landscape 报告、这药在哪几个国家在做临床、投资人问 X 有哪些在跑的临床。禁用于：查单个 NCT 的方案——那用 ctgov_detail 直答。
---

# 临床试验 landscape（trial-landscape）

面向两类用户：药企 / 投资人的**竞争情报**，学者的**试验设计参考**。共用一个流程，报告角度不同。

## 触发后先明确

1. **视角**：药企 pipeline / 投资人 landscape / 学者 benchmark / 患者 recruitment。
2. **范围**：单个化合物？单个靶点？单个适应症？还是 X drug × Y indication 组合？
3. **时间窗**：只看 recruiting / active，还是也含 completed 3 年内？

## 工作流

### Step 1：靶点 / 药物规范化

- 药物 → `chembl_compound_search` 拿 ChEMBL ID → `ot_drug_details` 拿 tradeNames / synonyms
- 靶点 → `hgnc_lookup_symbol` 拿 symbol + alias（**alias 一定要一起搜**，同一靶点在不同厂商标签里名字不同）
- 疾病 → `ols_search` ontology=mondo 拿 MONDO ID + synonyms

搜索时**用 synonym 集合并集**，不是只用规范名。

### Step 2：拉试验

**药物视角**：`ctgov_search` intervention=<drug + synonyms>
**靶点视角**：先 `ot_target_associated_diseases` 拿疾病列表 → 逐疾病 `ctgov_search` intervention=<any modulator>（这个覆盖率会不完美，要在报告里明说）
**竞争情报**：`ctgov_by_sponsor` 按公司名拉全 pipeline

### Step 3：分层表格

按 phase 分四行（Phase 1 / 2 / 3 / 4）×  按 status 分三列（recruiting / active / completed）。每格里放 NCT 数量 + 展开链接。

```
              recruiting   active     completed
Phase 1          3            2         5
Phase 2          4            3         12
Phase 3          1            2         8
Phase 4          0            0         3
```

### Step 4：endpoint 归一化

`analyze_endpoints`（如果 CT.gov API 支持——CSSwitch 里没直接暴露，用 `ctgov_detail` 拿每个 NCT 的 primary_outcomes 逐个抽）。产出"这个适应症里被用过的主要终点"清单：
- overall survival (OS)
- progression-free survival (PFS)
- objective response rate (ORR)
- disease-free survival (DFS)
- 具体量表（EDSS、HAM-D 等）

按被用次数排序 —— 用户设计新试验时可参考惯例。

### Step 5：KOL / 站点

对 top-5 recruiting 的试验：
- `ctgov_detail` 拿 locations 列表
- 提取 principal investigator（如果 API 返回）+ 机构
- 出现频次高的 = **该领域 KOL**

**警告**：不要仅凭出现次数评级"影响力"——用户可能拿去做 KOL 邀请，凭 CT.gov 挂名判断影响力风险很高。至多说"XX 教授在 5 个 recruiting 试验中挂 PI，可作为 KOL 候选"。

### Step 6：产出报告

三段结构：
1. **Landscape overview**：数量表 + 3 个关键发现（如"过去 24 个月新启动的 3 期试验都聚焦 second-line"）
2. **Endpoint benchmark**：主要终点频率表，按 phase 分
3. **Competitive gaps**：哪些患者亚组 / geography / phase 没有 active trial（=机会窗口 or 未满足需求）
4. **数据局限**：CT.gov 覆盖以美国为主，欧洲 EudraCT / 中国 CDE / 日本 JAPIC 没打通——报告里明说。

## 反例

**编 NCT ID** = 死罪。CT.gov 的 NCT ID 特别容易被 LLM 幻觉，因为格式很规律（8 位数字）。任何 NCT ID 都必须从 `ctgov_*` 工具的输出里来，不能自己写。**同理不允许伪造 PI 名字**。

## 边界

- 只覆盖 ClinicalTrials.gov（美国 NIH 注册库）。EudraCT / CHiCTR / ANZCTR 不在。
- Sponsor 名字规范化很粗（大公司会有几十个法律实体名），需要用户手工核对。


## 收尾强制项：不确定性面板（uncertainty-first）

**本工作流的结论一律不得省略五段面板**：Known knowns / Known unknowns / Conflicts / Missing data / Next experiment。做法见 `uncertainty-first` skill —— 优先把结论拆成 claim 走 `evidence_graph`（每条 claim 自动绑证据等级 / 物种 / 样本量 / 疾病阶段 / 适用边界 / 反证），再把 `claims` 喂给 `uncertainty_ledger` 自动生成五段，补上工具挖不到的领域先验（`extra` 参数）后原样贴出。缺这五段，回答视为未完成——研究者要的正是被暴露的盲区。
