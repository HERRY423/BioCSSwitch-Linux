---
name: geo-triage
description: 用于 GEO / SRA 公共转录组数据集的初筛与二次分析规划——选数据集、差异表达、富集分析、通路注释。触发：GEO 数据集、GSE、公共转录组、bulk RNA-seq 分析、differential expression、DEG 分析、GSEA、富集分析、pathway enrichment、KEGG、GO 富集、reanalyze GEO、找一个数据集来验证、公共数据验证我的假设、reanalysis of public data。禁用于：单细胞（scRNA-seq）分析——那需要 Seurat/Scanpy 全流程，本 skill 不覆盖。
---

# GEO 数据集初筛与分析规划（geo-triage）

**这个 skill 不跑分析，它帮你选数据和规划分析**。真跑分析要在用户自己的机器上，Skill 会产出可执行的 R / Python 脚本。

## 触发后先问

1. **要验证什么假设？**——不是"看看有没有数据"，是"我怀疑 X 基因在 Y 病里上调"这类可证伪陈述。假设不清就先帮用户把它写清。
2. **哪种数据可以接受？**——bulk RNA-seq / microarray / bulk proteomics / methylation ...
3. **样本量下限？**——n<10 的数据集用来发现 hypotheses 尚可，用来发论文级证据风险太高。默认 n≥15/组。
4. **物种？**

## 工作流

### Step 1：找数据集

`geo_search` 用组合 query：
```
(<disease>[Title/Abstract]) AND (expression profiling by high throughput sequencing[DataSet Type] OR expression profiling by array[DataSet Type]) AND ("<species>"[organism])
```

再 `geo_summary` 拉候选的 title / sample_count / platform / submission_date。

### Step 2：粗筛表

产出一张表，用户勾：

| GSE | 标题（15 字内摘要）| n | 平台 | 年份 | 提示 |
|---|---|---|---|---|---|

"提示"列列出：
- **样本量偏小**（n<15/组）
- **无对照**（只有病人组，无 healthy control 或 baseline）
- **过时平台**（Affymetrix HG-U133A 这类旧芯片，结果可能与新一代 RNA-seq 有偏差）
- **未公开原始数据**（只有 processed matrix）

### Step 3：验证候选数据集的可用性

对用户勾选的 GSE：
- 说明设计：`treatment vs control`? paired？time-course？
- 提示 batch effect 风险（不同 GSM 是不是同一天测的？——GEO metadata 里的 submission_date 只是上传日）
- 检查是否已经在 recount3 / ARCHS4 里被 reprocess 过（如果是，可以直接拿 harmonized counts）

### Step 4：生成分析脚本骨架

按用户选的 GSE 类型，产出以下之一：

**RNA-seq (raw counts available)** → R + DESeq2 脚本：
```r
library(DESeq2)
dds <- DESeqDataSetFromMatrix(countData=counts, colData=meta, design=~condition)
dds <- DESeq(dds)
res <- results(dds, contrast=c("condition","case","control"))
# 保守阈值 padj < 0.05 & |log2FC| >= 1
sig <- res[which(res$padj < 0.05 & abs(res$log2FoldChange) >= 1), ]
```

**Microarray (already normalized)** → R + limma 骨架。

**Enrichment** → clusterProfiler / gseapy 骨架，明确用什么 gene set：
- MSigDB Hallmark（宽视野入门）
- KEGG（通路 mechanism）
- Reactome（更细的 pathway 拓扑）
- GO BP（生物过程）

### Step 5：结果解读约束

用户跑完带回结果时，你必须：
- 追问是否做了 batch correction（`sva::ComBat` / `limma::removeBatchEffect`）
- 不接受"top-10 DEG 都很合理"这种描述——要看 volcano plot 的整体分布
- 富集结果的 padj 阈值和 gene set 大小（<15 或 >500 的 term 可解释性差）
- 若结果与用户假设一致，**多问一句"有没有 negative control gene"**——防止 confirmation bias

## 反例

用户："GSE12345 的 DEG 是什么？" 你不查数据就编 5 个 gene symbol —— 严禁。GEO 具体的 processed matrix 不在 CSSwitch 里，你只有 metadata。DEG 让用户自己跑（脚本你给）。

## 边界

- 单细胞 scRNA-seq、空间转录组、metabolomics 不在本 skill 覆盖。
- SRA 原始 fastq 需要用户自己拉（`prefetch` / `fasterq-dump`），本 skill 不代跑。


## 收尾强制项：不确定性面板（uncertainty-first）

**本工作流的结论一律不得省略五段面板**：Known knowns / Known unknowns / Conflicts / Missing data / Next experiment。做法见 `uncertainty-first` skill —— 优先把结论拆成 claim 走 `evidence_graph`（每条 claim 自动绑证据等级 / 物种 / 样本量 / 疾病阶段 / 适用边界 / 反证），再把 `claims` 喂给 `uncertainty_ledger` 自动生成五段，补上工具挖不到的领域先验（`extra` 参数）后原样贴出。缺这五段，回答视为未完成——研究者要的正是被暴露的盲区。
