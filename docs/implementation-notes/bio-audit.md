# bio-audit — implementation-notes

**目的**：告诉使用者本 pack 里"什么已验、什么没验、什么可信、什么别信"。

## 已实现（可以指望它）

- `evidence_verify(claims)` 逐条打到 **PubMed / Crossref / ClinicalTrials.gov** 校验 ID 真实性。
  - PubMed：走 `efetch` 拉 XML，解析 title / abstract / DOI / publication_types。
  - Crossref：走 `/works/{doi}`，取 title / journal / year / author。
  - CT.gov：走 v2 `/studies/{nct_id}`，取 status / phase / study_type / enrollment。
- 证据类型分类**只从 MeSH publication_types / CT.gov study_type 推**，不做标题启发式（防止 title 里出现 "randomized" 就升级为 RCT）。
- Species mismatch 警告：claim 中出现 "patient / adult / clinical"，参考文献 title/abstract 出现动物模型关键词，就在返回里加一条 `warning`。
- `evidence_build_table(audited_claims)` 输出 Markdown 表，中英文可选。
- 缓存：`~/.csswitch/cache/audit_*/`，PMID/DOI/NCT 7 天 TTL；同一 ID 重复查只打上游 1 次。

## Skill：`evidence-audit`

- SKILL.md 触发词覆盖医学 / 临床 / 药物 / 疗效等场景。
- 强制流程：草稿 → 打点引用 → `evidence_verify` → 读审计结果 → `evidence_build_table` → 最终答复。
- 明确写了反例（不要挂假 PMID）+ 一份证据强度分级表。
- Skill 是否被 Science 加载依赖 `packs::SKILLS_REL` 路径正确 → 需先跑 phase-1 verification。

## 已知局限

- **中文文献不覆盖**：CBM / 万方无 API 公开客户端，本 pack 不查中文源；SKILL.md 也明说了。
- **物种/来源启发式是英文关键词**：中文 claim 目前不会触发 species warning。（TODO：加中文触发词表）
- **利益冲突（COI）不校验**：PubMed API 不返回 COI 段；如要检查需要拉 full text。
- **元数据不代表结论**：`evidence_verify` 只验"引用存在 + 类型分类"，不验"引用是否真支持 claim"。后者需要 LLM 判断，本工具无法做。

## 依赖的 phase-1 未验证事实

- MCP 配置路径（`mcp-servers.json`）—— 若不对，Skill 里 `evidence_verify` 工具压根不会挂进 Science。
- Skill 目录路径（`skills/`）—— 若不对，SKILL.md 不会被加载，模型不会自动走审计流程。

以上两条通过桌面 app「验证」面板的 canary smoke test 确认后可移除本节。

## 与其它 pack 的关系

- 强烈**建议同时启用 bio-lit**：SKILL.md 里的检索步骤（`pubmed_search / europepmc_search`）来自 bio-lit。缺 bio-lit，模型只能凭记忆写 PMID 再交 verify → 命中率低。
- **建议同时启用 bio-mcp-shim**：让远程 MCP 惯用工具名（`search_articles`）在 Skill 触发时也能命中。

## 测试

- 单元测试：`packs/_lib/entrez.py` 的 `parse_pubmed_xml` 有 fixture 覆盖（TODO：还没写，phase-3 加）。
- 集成测试：`test/bio_eval/cases.py` 的 `evidence_audit` case 会走完整调用链。
