---
name: evidence-audit
description: 回答任何医学/临床/药物/疗效/流行病学问题时使用。对每条医学结论强制绑定 PMID / DOI / NCT，区分证据类型（meta-analysis / systematic-review / RCT / cohort / case-control / observational / case-series / animal / in-vitro / narrative-review / guideline），并在答复末尾以 Markdown 证据表呈现。触发词包括：治疗、疗效、有效性、剂量、副作用、指南、荟萃分析、临床试验、诊断、预后、生存率、发病率、患病率、机制、药物、靶点、生物标志物、疫苗、随机对照、observational、RCT、meta-analysis、cohort、systematic review。也用于"这个 PMID/DOI/NCT 是真的吗"、"帮我核对这些参考文献"、"帮我列一张证据表"这类明确校验请求。
---

# 证据链与引用审计（evidence-audit）

医学场景比其它场景对错误引用的容忍度低得多。**说错一条剂量、编造一个 PMID，就是安全事故**。这个 skill 强制你按流程走完引用校验，答复前必须过一遍 `bio-audit-verify` MCP 工具。

## 铁律

1. **无引用则不下结论**。任何形如"X 能治 Y"、"A 比 B 好"、"发病率是 Z"这类事实性医学陈述，必须挂至少一条 PMID / DOI / NCT。如果你没有可引用的来源，就明确说"我没有可引用的证据支持这一点"，而不是含糊其辞。
2. **每一条引用都要过 `evidence_verify`**。哪怕你"记得"这个 PMID 是真的，也要过。这是防你自己幻觉的工具，不是给我看的形式主义。
3. **上游说不存在，就是不存在**。`evidence_verify` 返回 `exists=false` 时：撤回那条结论，或改标注为"未核实"。**绝不**换一个"看起来像"的 PMID、也**绝不**让工具"搜相似的"——那是二次幻觉。
4. **证据类型只信元数据**。工具返回的 `evidence_type` 是从 PubMed 的 MeSH publication_type 或 CT.gov 的 study_type 推出来的。不要用标题里的字眼（"randomized"）自行升级证据等级。
5. **物种/来源与结论对齐**。如果结论谈的是"人类患者"，但工具警告 `warning=动物实验/体外`，你要么改口为"临床前证据显示…"，要么把结论撤下来。
6. **利益冲突与局限也要写**。不是让你抄 disclosure 全文，是让你从元数据能看到的赞助方 / 研究设计限制里挑最要紧的一条讲。

## 工作流

**步骤 1：草稿**。先按用户问题自然作答，允许自己在心里列 3–8 个关键 claim。

**步骤 2：给每个 claim 找出你打算用的引用**。把它们组织成如下形式：

```json
{
  "claims": [
    {
      "text": "二甲双胍单药可显著降低 2 型糖尿病患者的心血管事件风险",
      "refs": [
        {"id_type": "pmid", "id": "9742976"},
        {"id_type": "pmid", "id": "31157855"}
      ]
    }
  ]
}
```

**步骤 3：调 `evidence_verify`** 一次性把所有 claim 送去校验。不要一次只查一条 —— 一次批量校验的开销更低。

**步骤 4：读审计结果**。对每条 claim 的 `verdict`：
- `supported` → 保留
- `partially_supported` → 挑出 `exists=false` 或有 `warning` 的引用，把它们从这条 claim 移除；如果剩余引用不足以支持结论，把结论降级或撤回
- `unsupported` → 撤回这条 claim，或明示"未找到可靠来源"

**步骤 5：调 `evidence_build_table`**，把审计后剩下的 claim 传进去，拿到 Markdown 证据表。

**步骤 6：给用户回话**。答复结构：
1. 一段自然语言的正文答复，每条医学结论后紧跟 `[PMID:xxxxx]` / `[DOI:xxx]` / `[NCT:xxxxxxxx]`。多个引用用 `; ` 分隔。
2. 一行 `**证据表**：`
3. Markdown 证据表（步骤 5 拿到的原样贴出，不要重排）。
4. 如果有任何 claim 被降级或撤回，最后写一段 `**审计说明**：`，用一两句话说明"原本还想说 X，但引用未通过校验，所以撤下"。这既是给用户的透明，也是防止你下次遇到相同问题时重复同样的幻觉。

## 引用格式规范

- **PMID**：仅数字，4–9 位。写作 `[PMID:12345678]`。
- **DOI**：`10.xxxx/yyy` 全串。写作 `[DOI:10.1016/S0140-6736(23)00001-1]`。DOI 里的括号、斜杠原样保留。
- **NCT**：`NCT` + 8 位数字。写作 `[NCT:NCT01234567]`。
- 每条医学 claim 尾部紧跟引用块，不要放到段末统一列。段末的"参考文献 [1][2]"格式更像论文投稿，读者对不上号。

## 证据类型分级（工具返回值一致）

从强到弱：

| 等级 | 类型 | 何时用 |
|---|---|---|
| A | `meta-analysis`, `systematic-review` | 综合了同类研究的定量/结构化综述 |
| B | `RCT`, `clinical-trial`, `guideline` | 随机对照或权威指南 |
| C | `cohort`, `case-control` | 观察性研究 |
| D | `observational`, `case-series` | 较弱的观察 / 病例系列 |
| E | `narrative-review`, `editorial`, `letter`, `comment` | 观点、评论、社论 |
| F | 无有效引用 / `unclassified` | 需要撤回或明示 |

如果一条结论只能挂 E 级引用，先想清楚是不是要下这个结论。E 级适合背景介绍，不适合直接支撑"应该怎么办"这种结论。

## 一个反例（不要这样）

> 二甲双胍降低乳腺癌复发率约 40% [PMID:99999999]。

问题：
- 99999999 大概率不存在。
- 数字"约 40%"来源不明。
- 没有告诉读者研究是 RCT 还是 observational。

正确做法：先 `evidence_verify`，若不存在就撤回；若存在就把 `evidence_type` 与年份写进证据表；40% 这个数字要在引用的文献里能找到具体来源（把它写清是哪个终点，例如 DFS or OS）。

## 边界

- 中文文献（万方 / CBM）目前不在本 skill 覆盖范围。要引中文文献时明示"未通过 CSSwitch 引用审计"，让用户自行核对。
- 预印本（bioRxiv/medRxiv）**可以引**，但必须标注 `preprint (未经同行评审)`，且证据类型统一记为 `preprint`，不能记为 RCT 等。
- 对话式追问时，之前审计过的引用不必重新校验；**新提出的**引用一律要过一次。

## 触发时如何调用

用户问："阿司匹林一级预防对健康人心血管事件的作用？"

1. 你调用 `pubmed_search` 拿候选文献（如果没装 bio-lit，可以直接从记忆写候选 PMID）。
2. 你把候选 PMID 打包给 `evidence_verify`。
3. 你把审计后合法的 claim 送 `evidence_build_table`。
4. 你按上面「答复结构」输出。

如果 `bio-audit-verify` MCP 不可用（工具列表里没有 `evidence_verify`），**立刻在答复顶端**加一句 `⚠️ 引用审计工具未连接，以下内容未经自动校验`，然后照常回答但**不要**编造 PMID / DOI / NCT。


## 深度模式：Claim 级证据图（evidence_graph / evidence_profile）

`evidence_verify` 回答的是「引用真不真」。当结论需要**适用边界**与**反证**时，升级到 claim 级证据图：

- `evidence_profile(id_type, id)` —— 单篇深挖：物种 / 人群（年龄性别）/ 样本量 / 实验类型（临床 II 期 · 动物 · 体外 · 回顾性队列）/ 疾病阶段，每个推断都带 signals（凭哪条 MeSH / 摘要片段得到），不是黑盒。
- `evidence_graph(claims)` —— 主力：每条 claim 绑证据后自动算出：① 证据等级 ② **适用边界**（物种/人群/阶段/样本量）③ **conflicts**（含"断言人类但证据是动物"这类错配、方向相反的反证）④ **counter_evidence**（你用 `stance:"refutes"` 标注的反例引用）。返回机器可读的 nodes/edges 图 + 每条 claim 的 verdict（supported / contested / unsupported）。

用法：把 claim 拆好，给每条 claim 标 `asserted`（这条隐含断言的物种/人群/干预/终点）和 `refs`（每条引用标 `stance` = supports / refutes）。工具会把「你以为的」和「证据实际支持的」对齐，错配处标红。

**结论必须落成这样**（正是需求要的形态）：

> 结论 A 由 PMID1 / PMID2 / NCT3 支持，证据等级为 **临床 II 期 / 动物 / 体外 / 回顾性队列**，适用边界是 **人类 · 转移性 · n≤245**，反例在 **PMID4（方向相反的回顾性队列）**。

最后把 `evidence_graph` 的 `claims` 直接喂 `uncertainty_ledger`，产出五段不确定性面板（见 uncertainty-first skill）。
