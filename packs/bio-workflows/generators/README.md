# bio-workflows/generators — 高质量科研工作流生成器

**不是"给 LLM 一个提示词让它写"的层次**。这些是**确定性 CLI 工具**，跑一遍就产出真实可用的中间产物：MeSH boolean 检索式、CT.gov landscape markdown、druggability 评分卡、DESeq2 R 脚本。LLM 可以调用它们，用户也可以直接 Python 跑。

## 现有生成器

| 脚本 | 场景 | 产物 |
|---|---|---|
| `sr_pico_builder.py` | 系统综述 / SR 前置检索 | 三条真实检索式：PubMed / Europe PMC / Cochrane。所有 MeSH 词从 NCBI 拉，不猜 |
| `ct_landscape.py` | 临床试验 landscape / 竞争情报 | Markdown 报告：phase×status 矩阵 + endpoint 频率 + sponsor / 地理分布 + NCT 清单 |
| `td_druggability.py` | 靶点 druggability 评级 | 评分卡：结构类别 + ChEMBL 活性 + Open Targets 药物 → A/B/C/D 评级 + 可核对链接 |
| `omics_deseq2.py` | RNA-seq DEG + GSEA | R 脚本（DESeq2 + apeglm + clusterProfiler + Hallmark GSEA），含 QC / volcano / heatmap / batch 自动处理 |

## 设计原则

**每个生成器都遵循同样的三条**：

1. **数据从真实上游拉**。sr_pico_builder 的 MeSH 词查 NCBI；ct_landscape 拉 CT.gov v2；td_druggability 拉 HGNC + UniProt + ChEMBL + Open Targets。任何"AI 编"的字符都是失败。
2. **可反查**。每一条结论指到一个 URL。td_druggability 报告底部列 UniProt / ChEMBL / Open Targets 直链，方便用户手工核对。
3. **不代跑分析**。omics_deseq2 产出 R 脚本，用户在自己机器上跑 —— 结果、图、tsv 全落到用户磁盘。这样：
   - 不占 CSSwitch 计算资源
   - 用户自己看得到中间对象（rds），可 reproducibility
   - Session info 落文件，跨机器复现有依据

## 与 pack / MCP 的关系

现在这些生成器是**独立 CLI**，不通过 MCP 暴露。原因：

- Skill 触发时 LLM 已经能通过 `pubmed_search` / `ctgov_search` 等 MCP 工具做同样的事，但**质量参差**（会被参数误导 / 编 NCT）。
- 生成器是"给这一步定死答案"的方式：Skill 里让 LLM 告诉用户"我们用 sr_pico_builder 生成检索式"，然后建议用户跑一下 CLI —— 不让 LLM 自己组检索式。

**未来演进**：如果 phase-1 canary 验证 MCP 路径可信，可以把生成器包装成 MCP tool，Skill 直接调。但**不着急**——现有 CLI 已经能被 shell 或 Python 用户直接用。

## 与 workflow Skills 的关系

- `lit-review` Skill → 建议 `sr_pico_builder`
- `trial-landscape` Skill → 建议 `ct_landscape`
- `target-discovery` Skill → 建议 `td_druggability`
- `geo-triage` Skill → 建议 `omics_deseq2`（DEG 阶段）

在 Skill 文本里让 LLM **说清楚"下一步请跑这个脚本"**，把生成检索式 / 分析代码的责任外包给确定性工具。

## 依赖

Python: 只用 `_lib/`（stdlib-only）+ 各生成器自己所需上游 API。

R（omics_deseq2 输出脚本需要）：
```r
BiocManager::install(c(
  "DESeq2","apeglm","clusterProfiler","org.Hs.eg.db",
  "msigdbr","enrichplot","EnhancedVolcano","pheatmap"
))
```

## 测试（fixture + golden）

**已有离线 golden tests**，CI 默认零网络：

```
# 离线跑（用 test/generators/fixtures/ 回放，与 golden/ 比对）
python test/generators/test_generators_golden.py

# 改了 generator 逻辑后刷新 golden
python test/generators/test_generators_golden.py --update-golden

# 网络集成测试（手动，只校验结构不变式，不比对 golden）
python test/generators/test_generators_golden.py --live
```

fixture 分两种来源：

| 来源 | 脚本 | 用途 |
|---|---|---|
| 合成（离线，CI 默认） | `test/generators/synth_fixtures.py` | 手写最小但结构正确的响应体；键由真实请求路径生成，保证 replay 命中 |
| 真实录制（高保真） | `test/generators/make_fixtures.py --live` | 从真实 NCBI / CT.gov / HGNC / UniProt / ChEMBL / Open Targets 录，脱敏后入 git |

fixture 回放靠 `_lib/fixtures.py`：设 `CSSWITCH_HTTP_FIXTURES=<dir>` + `CSSWITCH_HTTP_FIXTURE_MODE=replay|auto|record`，`_lib/http.py` 会拦截所有请求。**录制时自动脱敏** `api_key / token / mailto / email` 等键，fixture 可安全入 git。

覆盖：MeSH esearch/esummary、HGNC fetch、UniProt entry、ChEMBL target_search/activity、Open Targets GraphQL、CT.gov studies —— 每个数据源 1–2 个代表 fixture。

**bio_eval 的 tool loop 也用同一套 fixture 机制**（`CSSWITCH_HTTP_FIXTURES` 一激活，工具执行全离线）。
