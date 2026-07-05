---
name: lit-review
description: 用于文献综述 / systematic review / scoping review / narrative review / meta-analysis 前置检索。触发：帮我做文献综述、写综述、systematic review、scoping review、meta-analysis、PRISMA、搜一下最近 5 年、这个领域现在有哪些证据、把 X 的文献理一遍、literature review on、review the evidence for、我要写一个 review、帮我系统地看一下、grade the evidence。禁用于：只查单篇、翻译摘要这类微任务——那些直接答就行，别启动这个流程。
---

# 文献综述（lit-review）

综述质量的分水岭不是找到了多少篇，而是**边界清晰 + 排除有据 + 证据分级**。这个 skill 让你按 PRISMA 精神来（不强求 22 条完整对齐，但关键节点不能省）。

## 触发后你的第一句话

先问用户 4 件事，别抢答：

1. **研究问题（PICO 或 PECO）**——人群 / 干预（或暴露）/ 对照 / 结局。用户说不清就用他们的原话再逼一遍。
2. **纳入 / 排除标准**——时间范围、语言、研究设计（RCT only？含 observational？）、物种（人？也含动物？）。
3. **想要几层深度**——快速 scoping（30 分钟看完）？还是像 SR 那样每篇都拉全文？
4. **有没有已有的关键文献**——用户手里的 3–5 篇「种子文献」是最好的检索校准。

## 工作流

**Step 1：检索**。同时打三源：
- `pubmed_search` 用 MeSH + Title/Abstract 组合，构造 boolean query。给用户看 query 让他确认，不确认不往下走。
- `europepmc_search`（含 preprint / PMC 全文，覆盖 PubMed 漏的）
- `crossref_search`（覆盖非 PubMed 索引的期刊）

三源命中去重（按 DOI / PMID），把只在一个源出现的用 `⚠ 单源` 标出。

**Step 2：种子文献扩散**。对用户提供的种子 PMID：
- `pubmed_related` 拿相关文献
- `europepmc_citations` 拿谁引了它
两条路线交集里出现的高频文献 = 领域核心。

**Step 3：粗筛**。给用户一个表格（每行 25 字以内标题 + 年份 + 类型 + 一句是否入选的理由），让他勾。**别自动决定**——排除依据必须记录，PRISMA 表就是这个用途。

**Step 4：细筛 + 证据分级**。对入选的每一篇：
- `pubmed_fetch` 拿摘要与 `evidence_type`
- 明确写 study design、n、主要终点、局限
- **调用 `evidence-audit` skill**（如果启用了 bio-audit）走一遍引用校验

**Step 5：合成**。产出：
1. PRISMA-lite 流程图（文本描述即可，四层：identified → screened → assessed for eligibility → included）
2. 证据表（`evidence_build_table`）
3. 冲突结论段落：如果不同研究结论矛盾，明确指出、按证据等级排序
4. 局限性一段（**必写**，不写等于对读者不负责）

## 反例

用户说"综述一下阿司匹林一级预防"，你直接给一段 500 字总结完事——这不是综述，是背诵。综述必须有**检索 query、纳排、评级、冲突**四件套。

## 边界

- 全文获取受限：EPMC `europepmc_fulltext` 只拿 OA；非 OA 论文你只能引摘要，别装作看过全文。
- 中文文献（万方 / CBM）未覆盖，用户明确要中文时明说"CSSwitch 目前不含中文数据源，建议手动补充"。


## 收尾强制项：不确定性面板（uncertainty-first）

**本工作流的结论一律不得省略五段面板**：Known knowns / Known unknowns / Conflicts / Missing data / Next experiment。做法见 `uncertainty-first` skill —— 优先把结论拆成 claim 走 `evidence_graph`（每条 claim 自动绑证据等级 / 物种 / 样本量 / 疾病阶段 / 适用边界 / 反证），再把 `claims` 喂给 `uncertainty_ledger` 自动生成五段，补上工具挖不到的领域先验（`extra` 参数）后原样贴出。缺这五段，回答视为未完成——研究者要的正是被暴露的盲区。
