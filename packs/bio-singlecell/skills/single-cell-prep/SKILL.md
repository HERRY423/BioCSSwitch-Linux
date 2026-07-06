---
name: single-cell-prep
description: 用于单细胞 RNA-seq 数据的标准化预处理、QC、doublet 检测、batch 整合、基因 ID 转换、细胞类型注释与内容指纹，为下游聚类、scFM embedding、DEG、轨迹或细胞通信准备可复现输入。触发：单细胞预处理、scRNA-seq QC、scanpy 预处理、AnnData、h5ad、质控、doublet、Scrublet、scDblFinder、batch correction、Harmony、scVI、BBKNN、基因 ID 转换、CellTypist、SingleR、CITE-seq、multiome、空间转录组、Visium。禁用于：bulk RNA-seq（用 geo-triage / omics_deseq2），以及 embedding 之后的 DEG/trajectory/cell communication（交给 sc-downstream-analysis）。
---

# 单细胞预处理与指纹（single-cell-prep）

本 skill 负责把 scRNA-seq 数据整理成**可复现、可追溯、适合进入下游分析**的状态。它不在对话里代跑 scanpy / scvi-tools / R；只生成参数、脚本与 provenance 骨架，让用户在自己的机器上运行。

## 铁律

1. **参数即数据**。filter / normalize / HVG / doublet / batch / annotation 的参数都要落进 `recipe_hash`。
2. **输入要指纹**。任何建模或下游分析前，先 `anndata_fingerprint`，并让用户本地计算真·内容哈希。
3. **QC 阈值可解释**。用 MAD-based（median ± n×MAD），讲清楚剔除规则。
4. **不代跑**。只产出脚本；不能声称已经算出 cluster 数、marker、DEG 或 doublet 数量。

## 工作流

**Step 1：了解数据**。确认物种、assay、细胞数、基因 ID 类型、是否有 raw counts、是否多 batch、是否 CITE-seq / multiome / spatial。

**Step 2：指纹**。调用 `anndata_fingerprint(descriptor=...)`，拿元数据指纹和真·内容哈希 snippet。

**Step 3：QC 阈值**。调用 `sc_qc_thresholds(stats=...)`，用每指标 median/MAD 给出阈值。

**Step 4：doublet 检测**。需要 10x / droplet 数据时调用 `sc_doublet_recipe`。默认 Scrublet；R 用户或 Bioconductor 管线可选 scDblFinder。

**Step 5：预处理配方**。调用 `sc_preprocess_recipe(target_model=...)`。Geneformer 不做 log/HVG，scGPT 要 HVG + value binning，generic 走标准 scanpy。

**Step 6：batch 整合**。多批次数据调用 `sc_batch_recipe`。简单 batch 先 Harmony；复杂跨协议优先 scVI；大规模可考虑 BBKNN；跨数据集 merge 可用 Scanorama。

**Step 7：基因 ID 转换**。如果下游模型、富集或参考集需要不同 ID，调用 `sc_geneid_convert`。必须保留 unmatched / multimapped 审计表。

**Step 8：细胞注释**。聚类/embedding 后调用 `sc_celltype_recipe`。CellTypist / SingleR / marker-based 都要输出置信度或交叉表，不把注释当作事实。

**Step 9：特殊模态**。CITE-seq / multiome 用 `sc_multimodal_recipe`；Visium / MERFISH / Slide-seq 用 `sc_spatial_recipe`。

**Step 10：交接**。如果用户要 embedding，交给 `scfm-embed`；如果要 DEG、轨迹、RNA velocity、细胞通信、marker/enrichment，交给 `sc-downstream-analysis`。

## 反例

> 我帮你去掉了 doublets、整合了 batch，并发现了 8 个 cluster，其中 cluster 3 是 T cell。

问题：在对话里假装完成计算，没给 recipe_hash、没保留输入指纹，也没有用户本地运行产生的结果文件。

## 边界

- 本 skill 只生成配方与脚本，不安装或运行 scanpy / scvi-tools / Scrublet / R 包。
- DEG、trajectory、RNA velocity、cell-cell communication、marker gene discovery、富集分析属于 `bio-sc-downstream`。
- scFM embedding 的运行骨架与 provenance 属于 `bio-scfm`。
- bulk GEO DEG/GSEA 属于 `geo-triage` 和 `omics_deseq2`，不是单细胞流程。
