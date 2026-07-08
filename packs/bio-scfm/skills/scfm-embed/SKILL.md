---
name: scfm-embed
description: 用于用单细胞基础模型或 baseline（Geneformer、scGPT、CellFM、UCE、scVI、totalVI、MultiVI）生成 embedding skeleton、fine-tuning skeleton、embedding 质量评估配方、benchmark 验证/goal-loop 合约，并强制记录 provenance。触发：Geneformer、scGPT、CellFM、UCE、single-cell foundation model、scFM、cell embedding、细胞表征、单细胞基础模型、reference mapping、scGPT 微调、Geneformer fine-tuning、embedding quality、scIB、batch mixing、bio conservation、AUPRC、rare-cell detection、benchmark gate、单细胞 embedding provenance。禁用于：常规 QC / doublet / batch 前置处理（先用 single-cell-prep），或把这些模型当聊天问答。
---

# 单细胞基础模型 embedding（scfm-embed）

Geneformer / scGPT / CellFM / UCE 是**计算工具**，不是聊天模型。scVI / totalVI / MultiVI 是每份数据自训的 domain baseline。这个 skill 的任务是生成 skeleton、锁 provenance、安排质量评估，而不是在对话里假装跑模型或解释结果。

## 铁律

1. **不假装运行模型**。不能凭空说“模型判定这些细胞是 T cell”。只能给脚本骨架、运行要求和 provenance 结构。
2. **provenance 五件套缺一不可**：输入 AnnData 内容哈希、预处理参数哈希、模型版本/checkpoint、embedding 维度/输出哈希/pooling、运行环境 + seed。
3. **输入 ID 类型必须对**：Geneformer 要 Ensembl ID；scGPT / CellFM 多数走 symbol；UCE 要 protein ID / protein embedding 映射。
4. **foundation model 要配 baseline**。跑 Geneformer/scGPT/CellFM/UCE 时，建议至少配一个 scVI 系 baseline，避免只看漂亮 UMAP。
5. **fine-tuning 更严格**。必须记录训练集哈希、split、超参、训练曲线、最佳 checkpoint 和评估指标。
6. **benchmark 不能裸奔**。AUPRC/F1/embedding-quality 数字必须带 bootstrap CI、split hash、seed、leakage audit、ground-truth hash；foundation model 还要有 scVI/totalVI/MultiVI baseline。

## 工作流

**Step 1：输入与预处理**。从 `single-cell-prep` 拿 `anndata_fingerprint`、真·内容哈希和 `sc_preprocess_recipe` 的 `recipe_hash`。CellFM/UCE 需要时调用 `scfm_preprocess_recipe_ext` 补专用预处理。

**Step 2：选模型与 baseline**。调用 `scfm_registry` 或 `scfm_model_matrix`。说明 foundation model 与 domain baseline 的区别。

**Step 3：生成 embedding skeleton**。调用 `scfm_embed_plan(...)`。它返回 `runnable=false`、`artifact_type=skeleton`、带 SystemExit 护栏的脚本和 provenance 骨架。

**Step 4：可选 fine-tuning**。如果用户明确要微调 Geneformer/scGPT，调用 `scfm_finetune_plan`。这也是 skeleton，不可直接运行。

**Step 5：用户本地运行**。用户在自己的 GPU/CPU 环境补 TODO、钉版本、跑脚本，产出 embedding、output_sha256、metrics。

**Step 6：定稿 provenance**。用 `scfm_provenance_record` 生成正式记录，再用 `scfm_provenance_verify` 检查。

**Step 7：embedding 质量评估**。调用 `scfm_embed_quality` 生成 batch mixing / biology conservation / scIB 指标脚本。质量结果作为 provenance 附件，再交给 `sc-downstream-analysis`。

**Step 8：benchmark gate / goal-loop**。如果用户要比较 Geneformer/scGPT/CellFM/UCE 或做 rare-cell detection（例如 KRT17+），先调用 `scfm_benchmark_plan(...)` 生成“每模型一个 subagent”的任务边界、`SubagentStop` 验证合约和可选 α-sweep goal-loop。每个模型返回结果后，必须调用 `scfm_benchmark_verify(...)`；只有 `hook_decision=pass` 的结果才能进入图表或手稿。

## 正例

用户要 Geneformer reference mapping：先确认 var_id_type，必要时做 gene ID 转换；用 `sc_preprocess_recipe(geneformer)`；用 `scfm_embed_plan` 出 skeleton；提醒用户本地运行后填 output hash；再用 `scfm_embed_quality` 检查 batch mixing 和 cell type conservation。

用户要 KRT17+ rare-cell benchmark：用 `scfm_benchmark_plan(task="rare_cell_detection", rare_population="KRT17+ epithelial state", primary_metric="auprc")` 固定 split、GMM/marker-threshold ground truth、α grid 和 baseline；每个模型结果用 `scfm_benchmark_verify` 检查 AUPRC CI、seed、split、no-leakage 和 baseline 后再汇总。

## 反例

> 我已经用 scGPT 跑完了，cluster 3 是耐药 T cell，DEG 是 GZMB。

问题：没有运行环境、没有输出哈希、没有 provenance，也把 embedding 和下游 DEG 结果混为一谈。

> scGPT 的 rare-cell AUPRC 是 0.71，所以可以写进结果。

问题：没有 bootstrap CI、split hash、ground-truth hash、seed、leakage audit，也没有 baseline；不能进入下游结论。

## 边界

- 本 skill 不下载模型权重、不安装 torch/geneformer/scgpt/scvi-tools，不占用用户 GPU。
- QC、doublet、batch、gene ID、cell type annotation 前置步骤归 `single-cell-prep`。
- DEG、trajectory、RNA velocity、communication、marker/enrichment 归 `sc-downstream-analysis`。
