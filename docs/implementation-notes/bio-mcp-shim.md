# bio-mcp-shim — implementation-notes

## 已实现

四个 shim 覆盖远程 MCP 惯用工具名：

| 远程 MCP | 本地脚本 | 对齐的工具名 |
|---|---|---|
| pubmed | `pubmed_shim.py` | search_articles / get_article_metadata / get_full_text_article / find_related_articles / convert_article_ids / get_copyright_status / lookup_article_by_citation |
| clinical-trials | `ctgov_shim.py` | search_trials / get_trial_details / search_by_sponsor / search_investigators / analyze_endpoints / search_by_eligibility |
| chembl | `chembl_shim.py` | compound_search / target_search / get_bioactivity / get_mechanism / drug_search / get_admet |
| biorxiv | `biorxiv_shim.py` | search_preprints / get_preprint / get_categories / search_published_preprints / funder_search / get_statistics |

`ServerDef.aliases` 让本地 MCP 以 `bio-mcp-shim-<name>` **和** Anthropic 兼容名（`pubmed` / `clinical-trials` / `chembl` / `biorxiv`）**同时**挂进 mcp-servers.json。

## 已知不完美（诚实说）

工具名对齐是**语义对齐**不是**字节级对齐**。远程 MCP 的实际参数 schema 我没有一手证据（我只有 Anthropic 那边给出的"工具选择指南"文字），所以：

- **参数名和 default 值可能与远程有出入**。例如远程 `search_articles` 是不是叫 `query`、还是 `q`、还是 `keywords`，我按 CSSwitch 前几版 bio-lit 的命名做的。
- **返回结构一定不同**。远程结果可能带 `article_id` / `rank`，我的返回结构照 E-utilities 原样解析。SKILL / Prompt 若期待某个字段名，需要用户自己适配。
- **不支持完整分页**。有些工具用简化 pageSize，缺 cursor 支持。

**结论**：把这层当"工具名不失配"用，不要当"字节级替身"用。如果 Skill / Prompt 里写死了某个返回字段，你可能会踩坑。

## smoke test

phase-1 canary 只验 `bio-mcp-smoke` 那一个 server 能被 Science 拉起。**不能证明** shim 里那 4 个 server 各自的工具都能被 Science 挂进工具列表——那需要用户在 Science 里发几句测试话，看 Claude 是否找到 `search_articles` 之类。

推荐流程：
1. 装 bio-mcp-shim + bio-lit（bio-lit 里 pubmed 也有相同工具名，一起装能对比）
2. 重启沙箱
3. 在 Science 里问：`用 search_articles 帮我查 metformin 的 meta-analysis`
4. 观察：模型是否发起了 `tool_use { name: "search_articles", ... }` 请求，工具执行有没有正常返回。

## 依赖

- `_lib/http.py` `_lib/entrez.py` `_lib/cache.py`
- 外部：PubMed E-utilities / Europe PMC / CT.gov v2 / ChEMBL data API v34 / bioRxiv API

## 冲突处理

若用户已手工挂了同名 MCP（比如自己写了 `pubmed`），`packs::apply` 保留用户的、跳过 alias 注册、在 warning 列写一条。本项目自己的长名（`bio-mcp-shim-pubmed`）仍会挂上。
