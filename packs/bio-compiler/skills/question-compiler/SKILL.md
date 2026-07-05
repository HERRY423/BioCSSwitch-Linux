---
name: question-compiler
description: 用于把模糊、开放式的科研问题先"编译"成结构化研究任务书，再开始检索。触发：这个靶点还有没有价值、X 在 Y 里值不值得做、帮我看看这个方向、这个药还能治什么、有没有新靶点、这个基因和这个病有什么关系、我想研究 X 但不知道从哪下手、帮我把问题理清楚、research question、把这个课题拆一下、这个方向可行吗、值得立项吗。禁用于：已经非常具体、可直接检索的单点查询（"查 PMID 12345 是不是真的"、"aspirin 对 COX-1 的 IC50"）——那些直接答或直接进对应工具就行。
---

# 研究问题编译器（question-compiler）

用户抛来的往往是一句模糊的话——"EGFR 在 GBM 里还有没有新靶点价值"。**直接去检索是错的**：没定义研究对象、终点、纳排、证据门槛，搜出来的东西无法收敛。这个 skill 强制你先把问题**编译**成结构化任务书，和用户确认后再动手。

## 铁律

1. **先编译，再检索**。任何开放式研究问题，第一步调用 `compile_research_question`，把结果读给用户，**不要**跳过直接搜。
2. **缺口必须回填**。编译结果的 `gaps` 和 `intervention.needs_user_input` 是硬性待办。在缺口未澄清前，只能做探索性预检索，不能下结论。
3. **不编实体**。编译器把没识别到的字段标 `needs_user_input` / `candidate`。你要么用 `disambiguate` 归一，要么问用户——**绝不**自己填一个"看起来对"的基因/疾病。
4. **结论阶段必过审计**。按 `recommended_toolchain` 走到最后，结论一定要经 `evidence_graph` + `uncertainty_ledger`（见 evidence-audit / uncertainty-first skill）。

## 工作流

**Step 1：编译**。调 `compile_research_question(question=用户原话)`。你会拿到：
研究对象 / 疾病（含本体提示）/ 分子 / 干预 / 终点 / 数据库 / 排除标准 / 证据门槛 / 推荐工具链 / 推荐 skill / gaps。

**Step 2：把任务书读给用户 + 逐条确认 gaps**。用一段结构化清单呈现，然后针对 `gaps` 和 `intervention` 逐条问。典型追问：
- 干预方式（靶点价值高度依赖成药方式：小分子抑制剂？抗体？ADC？降解剂？CAR-T？）
- 疾病亚型 / 分子分型 / 线数分期
- 时间窗、语言、是否纳入临床前
- 想要的深度（快速 scoping vs 系统评估）

**Step 3：归一化不确定实体**。对 `candidate` 置信度的基因/疾病，调 `disambiguate(term, context)` 确认；把本体提示（MONDO/EFO）落实为真实 ID。

**Step 4：交接到 workflow skill**。按 `recommended_skill` 进入对应模式（target-discovery / lit-review / trial-landscape ...），把编译好的任务书作为该 skill 的输入，不用再让用户重述。

**Step 5：执行 + 审计 + 暴露不确定性**。按 toolchain 跑；结论走 `evidence_graph`；最后必出 `uncertainty_ledger` 五段面板。

## 一个正例（EGFR / GBM）

用户："EGFR 在 GBM 里还有没有新靶点价值"

编译后你应当回：

> 我把这个问题编译成了任务书，请先确认几处再开搜：
> - **研究对象**：EGFR（基因/蛋白，高可信）× Glioblastoma（GBM, MONDO:0018177）
> - **问题原型**：靶点验证（target-validation）
> - **终点**：遗传学关联 / 功能依赖性(DepMap) / 成药性 / 临床先例
> - **数据库**：Open Targets · PubMed · ClinicalTrials.gov · ChEMBL · UniProt
> - **证据门槛**：需功能基因组学 + 临床关联双线证据；只有 text-mining co-mention 不足以说"有价值"
> - **待你确认**：① 干预方式？（EGFR-TKI 在 GBM 已多次失败，你问的是小分子、抗体、ADC[depatux] 还是 CAR-T？这决定结论）② 只看成人 GBM 还是含儿童 / IDH-mut 亚型？
>
> 确认后我按 target-discovery 流程执行，结论会给证据图 + 不确定性面板。

注意这里主动带出了"EGFR-TKI 在 GBM 屡次失败"这个领域先验——这正是编译阶段该逼出来的盲区。

## 一个反例（不要这样）

用户同样问 EGFR/GBM，你直接：`pubmed_search("EGFR glioblastoma")` 返回 20 篇摘要总结完事。
问题：没定义"新靶点价值"指什么终点、没区分干预方式、没设证据门槛、没暴露"EGFR-TKI 已失败"这个关键反例——用户拿到的是一堆文献，不是一个能立项的判断。

## 边界

- 编译器的识别是**启发式**：疾病靠缩写/中文词表，基因靠形状+已知靶点集，药物靠后缀+已知药名。覆盖不到的实体会标 `candidate`，别当成已确认。用 `compiler_capabilities` 可查当前覆盖范围。
- 编译器**不打网络、不做检索**，它只做结构化。真正的数据在后续 toolchain 里拉。
- 若 `bio-compiler` MCP 不可用（工具列表没有 `compile_research_question`），退化为手工按本 skill 的 Step 2 清单逐项和用户过一遍，同样不许跳过结构化直接搜。
