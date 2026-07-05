#!/usr/bin/env python3
"""RNA-seq 差异表达 + GSEA 完整脚本生成器（R + DESeq2 + clusterProfiler）。

**不代跑分析**。给用户一份**能直接跑**的 R 脚本，含：
  - 数据加载 (从 counts 矩阵 + coldata)
  - 质控（PCA / clustering / batch check）
  - DESeq2 归一化 + Wald 检验
  - shrinkage 用 apeglm
  - Volcano plot + heatmap top-N
  - clusterProfiler enrichGO / enrichKEGG / GSEA (Hallmark)
  - 保存所有中间对象（rds）方便复现

设计要点：
  - **保守阈值**：默认 padj<0.05 & |log2FC|≥1；用户命令行可覆盖
  - **明写 sessionInfo() + set.seed()**：可复现
  - **每步落一份图 + tsv**：方便复审
  - **batch correction 提示**：如果 coldata 里有 batch 列，脚本会自动加进 design

CLI：
    python packs/bio-workflows/generators/omics_deseq2.py \\
        --counts data/counts.tsv \\
        --coldata data/coldata.tsv \\
        --contrast condition tumor normal \\
        --out scripts/deseq2_tumor_vs_normal.R
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


R_TEMPLATE = r"""# ═══════════════════════════════════════════════════════════════════════════
# DESeq2 差异表达 + GSEA
# 生成器：CSSwitch bio-workflows/generators/omics_deseq2.py
# 生成时间：{ts}
#
# 输入：
#   counts    : {counts}
#   coldata   : {coldata}
#   contrast  : {factor}: {level_test} vs {level_ref}
#
# 输出目录：{outdir}/
#   - qc/                      PCA + sample distance heatmap + dispersion plot
#   - de/                      DEG 表 + volcano
#   - heatmap/                 top-N 表达热图
#   - enrichment/              GO / KEGG / GSEA 结果
#   - rds/                     所有中间 R 对象（复现用）
#   - sessionInfo.txt
#
# 阈值：padj < {padj} & |log2FoldChange| >= {log2fc}
# ═══════════════════════════════════════════════════════════════════════════

suppressPackageStartupMessages({{
  library(DESeq2)
  library(ggplot2)
  library(pheatmap)
  library(RColorBrewer)
  library(clusterProfiler)
  library(org.Hs.eg.db)   # 默认人类；小鼠改 org.Mm.eg.db
  library(msigdbr)
  library(enrichplot)
  library(EnhancedVolcano)
  library(apeglm)
}})

set.seed({seed})
outdir <- "{outdir}"
dir.create(file.path(outdir, "qc"),         showWarnings = FALSE, recursive = TRUE)
dir.create(file.path(outdir, "de"),         showWarnings = FALSE, recursive = TRUE)
dir.create(file.path(outdir, "heatmap"),    showWarnings = FALSE, recursive = TRUE)
dir.create(file.path(outdir, "enrichment"), showWarnings = FALSE, recursive = TRUE)
dir.create(file.path(outdir, "rds"),        showWarnings = FALSE, recursive = TRUE)

# ── 1. 载入 ─────────────────────────────────────────────────────────────
message(">> 1/6 载入 counts 与 coldata")
counts_raw <- read.table("{counts}", header = TRUE, row.names = 1,
                          check.names = FALSE, sep = "\t")
coldata    <- read.table("{coldata}", header = TRUE, row.names = 1,
                          check.names = FALSE, sep = "\t", stringsAsFactors = TRUE)
stopifnot(all(colnames(counts_raw) %in% rownames(coldata)))
coldata <- coldata[colnames(counts_raw), , drop = FALSE]
message(sprintf("   counts: %d genes × %d samples", nrow(counts_raw), ncol(counts_raw)))
message(sprintf("   coldata: %d samples, columns = %s",
                nrow(coldata), paste(colnames(coldata), collapse = ", ")))

# 因子 relevel：确保 ref 是对照
coldata${factor} <- relevel(as.factor(coldata${factor}), ref = "{level_ref}")

# ── 2. DESeqDataSet + 归一化 + 检验 ─────────────────────────────────────
message(">> 2/6 DESeq2 归一化 + Wald 检验")
has_batch <- "batch" %in% colnames(coldata)
design_formula <- if (has_batch) {{
  message("   检测到 batch 列，design = ~batch + {factor}")
  as.formula(paste0("~ batch + ", "{factor}"))
}} else {{
  as.formula(paste0("~ ", "{factor}"))
}}
dds <- DESeqDataSetFromMatrix(countData = round(counts_raw),
                              colData   = coldata,
                              design    = design_formula)
# 过滤极低表达 gene（≥ 10 counts in ≥ smallest_group 个样本）
smallest_group <- min(table(coldata${factor}))
keep <- rowSums(counts(dds) >= 10) >= smallest_group
message(sprintf("   保留 %d / %d 个 gene（过滤极低表达）", sum(keep), nrow(dds)))
dds <- dds[keep, ]
dds <- DESeq(dds)
saveRDS(dds, file.path(outdir, "rds", "dds.rds"))

# ── 3. QC ───────────────────────────────────────────────────────────────
message(">> 3/6 QC 图")
vsd <- vst(dds, blind = FALSE)
saveRDS(vsd, file.path(outdir, "rds", "vsd.rds"))

# PCA
pca_data <- plotPCA(vsd, intgroup = "{factor}", returnData = TRUE)
pv <- round(100 * attr(pca_data, "percentVar"), 1)
pdf(file.path(outdir, "qc", "pca.pdf"), width = 6, height = 5)
print(ggplot(pca_data, aes(PC1, PC2, color = {factor})) + geom_point(size = 3) +
      xlab(paste0("PC1 (", pv[1], "%)")) + ylab(paste0("PC2 (", pv[2], "%)")) +
      theme_classic())
dev.off()

# Sample distance heatmap
sdm <- as.matrix(dist(t(assay(vsd))))
rownames(sdm) <- paste(vsd${factor}, colnames(vsd), sep = ":")
colnames(sdm) <- NULL
colors <- colorRampPalette(rev(brewer.pal(9, "Blues")))(255)
pdf(file.path(outdir, "qc", "sample_distance.pdf"), width = 8, height = 7)
pheatmap(sdm, clustering_distance_rows = as.dist(sdm),
         clustering_distance_cols = as.dist(sdm), col = colors)
dev.off()

# Dispersion
pdf(file.path(outdir, "qc", "dispersion.pdf"), width = 6, height = 5)
plotDispEsts(dds)
dev.off()

# ── 4. DEG ──────────────────────────────────────────────────────────────
message(">> 4/6 差异表达")
res <- results(dds, contrast = c("{factor}", "{level_test}", "{level_ref}"),
               alpha = {padj})
# apeglm shrinkage 用于稳定 log2FC 排序（火山图 & 富集用它）
coef_name <- paste0("{factor}_", "{level_test}", "_vs_", "{level_ref}")
res_shrunk <- lfcShrink(dds, coef = coef_name, type = "apeglm")
res_out <- as.data.frame(res_shrunk)
res_out$symbol <- rownames(res_out)
res_out <- res_out[order(res_out$padj), ]
write.table(res_out, file.path(outdir, "de", "all_results.tsv"),
            sep = "\t", quote = FALSE, row.names = FALSE)

sig <- res_out[which(res_out$padj < {padj} & abs(res_out$log2FoldChange) >= {log2fc}), ]
message(sprintf("   显著 DEG: %d (up = %d, down = %d)",
                nrow(sig),
                sum(sig$log2FoldChange > 0, na.rm = TRUE),
                sum(sig$log2FoldChange < 0, na.rm = TRUE)))
write.table(sig, file.path(outdir, "de", "significant.tsv"),
            sep = "\t", quote = FALSE, row.names = FALSE)

# Volcano
pdf(file.path(outdir, "de", "volcano.pdf"), width = 8, height = 6.5)
print(EnhancedVolcano(res_out, lab = res_out$symbol, x = "log2FoldChange", y = "padj",
                       pCutoff = {padj}, FCcutoff = {log2fc}))
dev.off()

# Top-N heatmap
topN <- head(rownames(sig), {topn})
if (length(topN) >= 2) {{
  mat <- assay(vsd)[topN, , drop = FALSE]
  mat <- mat - rowMeans(mat)  # 减均值突出模式
  anno <- as.data.frame(colData(vsd)[, "{factor}", drop = FALSE])
  pdf(file.path(outdir, "heatmap", "top_deg.pdf"),
      width = 8, height = 0.15 * length(topN) + 3)
  pheatmap(mat, annotation_col = anno, cluster_rows = TRUE, cluster_cols = TRUE,
           show_rownames = length(topN) <= 60)
  dev.off()
}}

# ── 5. GO / KEGG / GSEA ─────────────────────────────────────────────────
message(">> 5/6 富集分析")

# gene symbol → ENTREZID
sig_entrez <- tryCatch(
  bitr(sig$symbol, fromType = "SYMBOL", toType = "ENTREZID", OrgDb = org.Hs.eg.db),
  error = function(e) NULL
)
if (!is.null(sig_entrez) && nrow(sig_entrez) > 0) {{
  # GO BP over-representation
  ego <- enrichGO(gene = sig_entrez$ENTREZID, OrgDb = org.Hs.eg.db,
                  ont = "BP", pAdjustMethod = "BH",
                  pvalueCutoff = 0.05, qvalueCutoff = 0.2, readable = TRUE)
  write.table(as.data.frame(ego), file.path(outdir, "enrichment", "go_bp.tsv"),
              sep = "\t", quote = FALSE, row.names = FALSE)
  pdf(file.path(outdir, "enrichment", "go_bp_dotplot.pdf"), width = 8, height = 7)
  if (nrow(as.data.frame(ego)) > 0) print(dotplot(ego, showCategory = 20))
  dev.off()

  # KEGG
  kegg <- enrichKEGG(gene = sig_entrez$ENTREZID, organism = "hsa",
                     pvalueCutoff = 0.05)
  write.table(as.data.frame(kegg), file.path(outdir, "enrichment", "kegg.tsv"),
              sep = "\t", quote = FALSE, row.names = FALSE)
}}

# GSEA (Hallmark)
res_ranked <- res_out[!is.na(res_out$stat), ]
gene_list <- res_ranked$stat
names(gene_list) <- res_ranked$symbol
gene_list <- sort(gene_list, decreasing = TRUE)

hallmark <- msigdbr(species = "Homo sapiens", category = "H")
term2gene <- hallmark[, c("gs_name", "gene_symbol")]

gsea <- GSEA(geneList = gene_list, TERM2GENE = term2gene,
             pvalueCutoff = 0.25, verbose = FALSE)
write.table(as.data.frame(gsea), file.path(outdir, "enrichment", "gsea_hallmark.tsv"),
            sep = "\t", quote = FALSE, row.names = FALSE)
pdf(file.path(outdir, "enrichment", "gsea_hallmark_dotplot.pdf"), width = 8, height = 6)
if (nrow(as.data.frame(gsea)) > 0) print(dotplot(gsea, showCategory = 20))
dev.off()

# ── 6. sessionInfo ─────────────────────────────────────────────────────
message(">> 6/6 sessionInfo")
writeLines(capture.output(sessionInfo()), file.path(outdir, "sessionInfo.txt"))
message("── 完成 ──  产物写入 ", outdir)
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", required=True,
                    help="TSV: gene id × sample raw counts")
    ap.add_argument("--coldata", required=True,
                    help="TSV: sample id × factor（含 condition，可含 batch）")
    ap.add_argument("--contrast", nargs=3, metavar=("FACTOR", "TEST", "REF"), required=True,
                    help='例：condition tumor normal → tumor vs normal')
    ap.add_argument("--out", type=Path, required=True, help="输出 R 脚本路径")
    ap.add_argument("--outdir", default="deseq2_out",
                    help="R 脚本内的输出目录（相对当前工作目录）")
    ap.add_argument("--padj", type=float, default=0.05)
    ap.add_argument("--log2fc", type=float, default=1.0)
    ap.add_argument("--top-n", type=int, default=50, help="Heatmap 的 top DEG 数")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from datetime import datetime
    factor, test, ref = args.contrast
    r_content = R_TEMPLATE.format(
        ts=datetime.now().isoformat(timespec="seconds"),
        counts=args.counts, coldata=args.coldata,
        factor=factor, level_test=test, level_ref=ref,
        outdir=args.outdir, padj=args.padj, log2fc=args.log2fc,
        topn=args.top_n, seed=args.seed,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(r_content, "utf-8")
    print(f"[omics_deseq2] R 脚本 → {args.out}")
    print(f"[omics_deseq2] 跑：Rscript {args.out}")
    print(f"[omics_deseq2] 输出会落到：./{args.outdir}/")
    print("\n必需的 R 包：")
    print("  BiocManager::install(c('DESeq2','apeglm','clusterProfiler','org.Hs.eg.db',")
    print("                        'msigdbr','enrichplot','EnhancedVolcano','pheatmap'))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
