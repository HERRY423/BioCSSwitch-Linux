---
name: reviewer-response
description: 用于写 rebuttal / point-by-point response to reviewers / R1 R2 修回信。触发：审稿意见、rebuttal、reviewer response、修回、response to reviewers、R1、R2、point-by-point、审稿人问、reviewer 说、reviewer 1 说、reviewer 2 意见、写回复信、修回信、给我一份 rebuttal、返修意见、我要回一个 reviewer。禁用于：写论文正文——那不是 rebuttal 的角色。
---

# Reviewer Response（reviewer-response）

**核心不是"辩赢"，是"让 reviewer + editor 觉得你把每一条都当回事、且改动可追溯"**。

## 触发后先要东西

**必须要到手才动笔**：

1. **完整的审稿意见**（原文，不是用户的转述——转述会漏细节）
2. **稿件当前状态**：R1？R2？editor 有没有额外意见？
3. **有没有硬拒的条目**（e.g., "本刊不接收 case series"）——有的话建议直接换刊，别浪费时间。
4. **改动清单**：用户已经准备做/不做哪些改。

**只给一段"reviewer 说数据不够"这类摘要**——先让用户把原话贴出来再走下一步。

## 结构模板

每条 reviewer comment 走三段式：

```
**Comment 1** (Reviewer 1, page 3): [原文，或摘要 + "原文如下：..."]

**Response**: [1–3 段回应]

**Changes in manuscript**: [具体页 / 行 / 段的改动，或 "no change – reasoning"]
```

## 分类应对

按 comment 性质分类应对（不同类要不同语气）：

### 类 1：Major - method 质疑

**必做**：
- 承认审稿人指出的具体问题
- 补充实验 / 补充分析 / 补充统计
- 如实在做不到，明确说"we agree this would strengthen the paper, but [具体理由]. Instead, we [补偿方案]"
- **绝不硬顶**。硬顶几乎都会被 desk-rejected on resubmission。

### 类 2：Major - conclusion 质疑

- 若你 believes conclusion 站得住，摆证据：`evidence-audit` 校验相关引用
- 若审稿人 point 有效，把 conclusion 降级（"suggest" 改 "may suggest"，"demonstrate" 改 "provide evidence for"）
- 附加 limitation 一段

### 类 3：Minor - 写作 / 图表

- 一律承认 + 改。写作和图表争议纯浪费彼此时间。
- 明确说改在哪：`Figure 2 has been redrawn with error bars showing 95% CI (page 12)`

### 类 4：Minor - 引用增补

Reviewer 常"暗示"你引用他/她的论文。判断：
- 相关且有价值 → 引，正常写
- 无关强推 → 礼貌不引：`We appreciate the reference. However, [ref] focuses on X while our work addresses Y; we chose to keep our reference list focused on directly relevant literature.`

### 类 5：Reviewer 之间冲突

- 明确指出两人意见冲突（editor 会看到，避免你被两头咬）
- 说明你的选择及理由
- 不要试图两边都讨好

## 工具协作

- 每次引用新文献支持你的答复：调 `evidence-audit` skill 校验 PMID / DOI 真实存在，别在 rebuttal 里挂假引用（reviewer 会查，一被查到基本没救）。
- 需要"相关工作"补充时：`pubmed_search` 用 reviewer 抱怨的 topic 关键词，找 3–5 篇最新的。
- 涉及临床试验对比时：`ctgov_search` 给 NCT 号，别口头描述。

## 语言基调

- **不要过度歉意**（"We deeply apologize for..."）——显得心虚。用中性的 "We thank the reviewer..."
- **不要抽象承诺**（"we will improve..."）——写具体改在哪。
- **不要贬低前作**（"unlike previous studies..."）——学术圈小，说别人不好没好处。
- **中英文都可写**，但同一封信只用一种语言。中文期刊也接受英文 rebuttal（若原文是英文）。

## 反例

用户："reviewer 说我数据不够，我想反驳。" 你不问原话不看数据，就写"数据其实是够的"—— 这就是把用户送进 desk reject 的做法。先问清楚。


## 收尾强制项：不确定性面板（uncertainty-first）

**本工作流的结论一律不得省略五段面板**：Known knowns / Known unknowns / Conflicts / Missing data / Next experiment。做法见 `uncertainty-first` skill —— 优先把结论拆成 claim 走 `evidence_graph`（每条 claim 自动绑证据等级 / 物种 / 样本量 / 疾病阶段 / 适用边界 / 反证），再把 `claims` 喂给 `uncertainty_ledger` 自动生成五段，补上工具挖不到的领域先验（`extra` 参数）后原样贴出。缺这五段，回答视为未完成——研究者要的正是被暴露的盲区。
