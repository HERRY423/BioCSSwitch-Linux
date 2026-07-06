---
name: sc-analysis
description: 端到端单细胞分析工作流，用于 scRNA-seq、10x Genomics、Scanpy 流程、Seurat 流程、单细胞全流程、单细胞差异表达、单细胞轨迹、RNA velocity、细胞通信、scFM embedding。负责串联 single-cell-prep、scfm-embed 与 sc-downstream-analysis。禁用于：bulk RNA-seq / microarray GEO 分析（用 geo-triage）。
---

# 端到端单细胞分析（sc-analysis）

本 skill 是路由器和工作流编排层。它把单细胞任务拆成前置准备、embedding/annotation、下游分析三个阶段。它不代跑分析，不编造结果，只生成配方、脚本和 provenance 链。

## 工作流

1. **理解数据**：来源、物种、组织、assay、细胞数、基因 ID 类型、是否多 batch、是否 CITE-seq / multiome / spatial。
2. **QC**：调用 `sc_qc_thresholds`。
3. **Doublet 检测**：调用 `sc_doublet_recipe`。
4. **预处理**：调用 `sc_preprocess_recipe`。
5. **Batch 整合**：如需，调用 `sc_batch_recipe`。
6. **基因 ID 转换**：如需，调用 `sc_geneid_convert`。
7. **降维 + 聚类**：给 scanpy 标准流程脚本，或建议 `sc_scanpy_pipeline.py` 生成完整脚本。
8. **细胞注释**：调用 `sc_celltype_recipe`。
9. **分支决策**：
   - 需要 scFM embedding → handoff to `scfm-embed`，用 `scfm_embed_plan` 和 `scfm_embed_quality`。
   - 需要 DEG → `sc_deg_recipe`。
   - 需要轨迹 / RNA velocity → `sc_trajectory_recipe`。
   - 需要细胞通信 → `sc_communication_recipe`。
   - 需要 marker / enrichment → `sc_marker_recipe` / `sc_enrichment_recipe`。
10. **结论收尾**：用 uncertainty-first 五段面板说明盲区。

## Do

- 先问清 raw counts、sample/condition/cell type/batch key。
- 每个阶段传递 `anndata_fingerprint`、`recipe_hash`、模型/脚本版本。
- 对 DEG 明确区分 pseudobulk 与 cluster marker。
- 对 trajectory / communication 明确“推断，不是实验证明”。

## Don't

- 不要把 bulk GEO / microarray 任务塞进单细胞流程。
- 不要在没有用户运行结果时编造 cluster 数、DEG、marker、细胞通信通路。
- 不要把细胞数当 biological replicate。
- 不要把 scFM embedding 当作自动解释器。

## 边界

- spatial 和 multiome 有专门配方，但完整空间+sc 联合建模不在本 skill。
- CELLxGENE 数据集检索可交给 `bio-sc-atlas`，真实下载在用户机器上。
- 下游结论如果引用文献或医学 claim，仍需走 `evidence-audit` / `uncertainty-first`。
