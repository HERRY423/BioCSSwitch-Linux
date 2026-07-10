---
name: grant-specific-aims
description: 用于写基金标书的 Specific Aims 页 / R01 aims / K award / NSFC 项目摘要 / significance section。触发：Specific Aims、aims page、NIH R01、R21、K award、NSFC、国自然、自然科学基金、基金标书、grant proposal、写标书、项目摘要、significance and innovation、grant aims、fellowship aims、专项基金申请书、青年基金、面上项目、重点项目。禁用于：全文 grant writing（那需要 methods / budget / biosketch，超出 skill 范围）。
---

# Grant Specific Aims（grant-specific-aims）

**一页 Aims 决定 90% 的评审第一印象**。核心不是"我做什么"，是"significance × innovation × feasibility 都能立起来"。

## 触发后先问

1. **哪类资助**？NIH R01 / R21 / K / NSFC 面上 / NSFC 青年 / EU Horizon / 其它。每类对篇幅、结构、评审关注点不同。
2. **申请人层级**：PI 已有 tenure？assistant prof？postdoc（K 或 fellowship）？—— 决定语气 preliminary data 的呈现方式。
3. **有 preliminary data 吗**？没有的话 R21/R33 或 exploratory 类更合适，别硬冲 R01。
4. **一句话核心 hypothesis**：说不清就先帮用户提炼。

## 结构：NIH 5 段式（其它资助按其模板调整）

### 段 1：Opening / Significance (5–7 句)

- 第一句：疾病 / 生物学问题的**未满足需求**（含 quantitative burden：n patients affected / mortality / cost）
- 第二句：**当前认知边界**（"despite recent advances in X, Y remains unclear"）
- 第三句：**gap 或 opportunity**（"a critical gap is..."）
- 结尾：本项目将填补 gap 的**总策略**

用 `pubmed_search` + `evidence-audit` 拉 3–5 篇最新支撑文献，别用 10 年以上的老引用做 significance。

### 段 2：Central Hypothesis + Rationale (3–5 句)

- Hypothesis 必须**可证伪**（"we hypothesize that A causes B via C"，而不是"we will investigate the role of A"）
- Rationale：为什么这个 hypothesis 有理由——preliminary data + published evidence 各占一半
- 引用 preliminary data 时具体到 figure（"we have shown (Fig. 1A) that..."）

### 段 3–5：Aims

每 Aim 一段，结构一致：
```
**Aim N: [8–15 字动词开头短句]**
[2 句 rationale + 3 句 approach]
Expected outcomes: [1–2 句]
Impact if successful: [1 句]
```

**Aim 独立性**：三个 Aim 不能"Aim 2 依赖 Aim 1 成功"这样串行——否则一个失败拖垮全项目。写成"parallel + converging"（各自独立成立、结果汇聚支持核心 hypothesis）。

**Aim 3 常见误区**：不要都做"in vivo validation"——评审会问"why can't you do the in vivo validation upfront"。Aim 3 更好放**机制探索** or **translational extension**（患者样本、临床相关性）。

### 段 6：Innovation + Impact (3–4 句)

- Innovation 分 conceptual（新假说 / 新框架）和 technical（新工具 / 新模型）
- Impact 说"if all aims succeed, we will…"——落在**下一代研究方向**上（"establishing a new therapeutic paradigm for…"）

## 工具协作

- **背景文献**：`pubmed_search` 用 "significance section keywords + last 5 years filter"；`evidence-audit` 全部 PMID 校验（**基金申请里挂假 PMID = 学术不端**，比 rebuttal 更严重）
- **靶点选择理由**（若涉及基因/蛋白）：`ot_target_associated_diseases` + `chembl_target_search` 证明"这个靶点有可 drug 化基础"
- **临床相关性**：`ctgov_search` 找当前的临床试验 landscape，Aim 3 里可以说"our findings would inform ongoing trials such as NCT..."
- **术语规范化**：`disambiguate` 检查你写的 gene symbol / disease name 是否有歧义——NSFC 中英文对照要求精确对应，同名歧义会被专家扣分。
- **提交前引用扫雷**：对最终 aims / significance 草稿运行 `packs/bio-audit/evidence_linter.py --strict <draft.md>`；任何 PMID / DOI / NCT 未通过验证都必须撤回或改写。基金申请里的假 PMID 比普通 rebuttal 更伤信用。

## Do / Don't

**Do**：
- 用现在时写 aims，"we determine" 而非 "we will determine"（现在时更 assertive）
- 每段第一句就是 punchline，不要铺垫
- 用「1 张 figure = 1 千字」的原则：Aims 页最多 1 张示意图（三段式概念图 / 项目框架图）

**Don't**：
- 别写"the mechanisms remain unknown" 作为立项理由（约 30% 的 aims 页开头都这样，评审免疫）
- 别用 "novel" 超过 2 次
- 别写"we will discover"（不确定的结果不能承诺）
- 别列 4 个及以上 Aim（R01 强烈建议 3 个，最多 3+1 sub-aim）

## 反例

用户："帮我写一个 R01 的 aims，做 X 基因和 Y 病。"
你直接写完整一版返回 —— 太早。至少问清楚 hypothesis、preliminary data、申请人层级三件事。

## 边界

- 本 skill 只写 Aims 页 / significance / innovation 三段。full grant（Methods / Rigor / Preliminary Data / Timeline / Budget）超出范围。
- 各资助的具体格式规范（页数、字号、行距）以官方指南为准，本 skill 只保证内容结构。


## 收尾强制项：不确定性面板（uncertainty-first）

**本工作流的结论一律不得省略五段面板**：Known knowns / Known unknowns / Conflicts / Missing data / Next experiment。做法见 `uncertainty-first` skill —— 优先把结论拆成 claim 走 `evidence_graph`（每条 claim 自动绑证据等级 / 物种 / 样本量 / 疾病阶段 / 适用边界 / 反证），再把 `claims` 喂给 `uncertainty_ledger` 自动生成五段，补上工具挖不到的领域先验（`extra` 参数）后原样贴出。缺这五段，回答视为未完成——研究者要的正是被暴露的盲区。
