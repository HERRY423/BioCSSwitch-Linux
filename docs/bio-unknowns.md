# Bio Unknowns —— 已知未验证 / 待逆向的清单

本项目的生医扩展有若干处**基于 Claude Code 惯例的猜测**尚未从 Claude Science 二进制侧确认。这份清单是**唯一权威**的追踪源；实际验证结果由用户在桌面 app 的「验证」面板触发的 smoke test 写回 `~/.csswitch/config.json` 的 `verification` 字段。

约定：
- `U`（**U**nverified）= 尚未验证，当前按猜测跑
- `S`（**S**moke pass）= 自动 smoke test 通过（可信度高）
- `M`（**M**anual confirm）= 用户手动确认（可信度中）
- `F`（**F**ail）= 已确认不对
- `V`（**V**erified by binary RE）= 从二进制逆向证据链得出（最高可信度）

## MCP 配置

| 项 | 现值（packs.rs） | 状态 | 证据 / TODO |
|---|---|---|---|
| MCP 配置文件相对路径 | `MCP_CONFIG_REL = "mcp-servers.json"` | `U` | 需 smoke test 或二进制 `strings claude-science \| grep -iE 'mcp.*(server\|config\|json)'` |
| MCP schema 顶层 key | `mcpServers` | `U` | Claude Code 惯例；未证实 Science 用同一 key |
| MCP server 三字段 | `command / args / env` | `U` | 同上 |
| MCP env 生效 | 环境变量注入到子进程 | `U` | 需 smoke test 里在环境变量里读 marker |

## Skill 目录

| 项 | 现值（packs.rs） | 状态 | 证据 / TODO |
|---|---|---|---|
| Skill 根目录 | `SKILLS_REL = "skills"` | `U` | 需触发 canary skill 手动确认（用户在 Science 里发触发词，看是否触发） |
| SKILL.md frontmatter 格式 | `name` + `description` | `U` | 与 Claude Code / Cowork skill 惯例一致；应大概率对，但没证 |
| 触发靠 description 关键词 | 是 | `U` | 若不对，只能用 `search_skills` 明示调用 |

## Provider 行为不定项

| 项 | 当前假设 | 状态 |
|---|---|---|
| DeepSeek v4-pro 遵守 `tool_choice: {type:"tool", name:"..."}` | 是（但见 DSML 泄漏） | `M` — DSML shim 已覆盖泄漏一类 |
| Qwen tools 保真 | 弱（`docs/verified-facts.md:40`）| `V` |
| GLM-4.6 长上下文承接 | 未知 | `U` |
| MiMo v2.5 pro 工具循环稳定性 | 未知 | `U` |
| 硅基流动的 `deepseek-ai/DeepSeek-V3` 与 DeepSeek 原生行为一致性 | 未知 | `U` |

## 生医数据源限制

| 项 | 说明 | 影响 |
|---|---|---|
| NCBI E-utilities 匿名限流 | 3 req/s；带 API key 上到 10/s | 已实现 rate limiter |
| Crossref polite pool | 需要 mailto | 已支持 `CROSSREF_MAILTO` |
| NLM DDI 端点 2024-01 关停 | RxNorm `interactions` 会 404 | 已在工具描述里说明 |
| bioRxiv API 无关键词搜索 | 只支持 DOI + 日期区间 | shim 走 Europe PMC `SRC:PPR` 兜底 |
| CT.gov v2 API 参数命名 | `query.cond / query.intr / filter.overallStatus` | 已实现；schema 若变化需更新 |
| Ensembl REST 限流 | 15 req/s 或 55000 req/hour | 尚未加限流；轻度使用 OK |

## 桌面 app 与 v0.3 profile 架构

| 项 | 说明 | 状态 |
|---|---|---|
| `packs::apply` 在 relay adapter 下工作 | 不感知 provider，只写 mcp-servers.json | `S`（逻辑上无关，但 smoke 未跑） |
| 非 active profile 探针 | 目前 `run_probes` 只支持 active | phase-2 修 |
| `sensitive_mode` 白名单黑清单 | 已内置公有 API host 拒绝列表 | `M` |

## 验证结果的环境指纹（phase-5）

`config.verification` 现在不只存 verdict，还存**通过时的环境指纹**：

| 字段 | 含义 |
|---|---|
| `science_version` | 验证通过时的 Claude Science 版本（`<bin> --version`） |
| `mcp_config_rel` | 通过时 `packs::MCP_CONFIG_REL` 的值 |
| `skills_rel` | 通过时 `packs::SKILLS_REL` 的值 |
| `python_path` | canary MCP 用的 python3 路径 |
| `last_marker` | 上次 canary marker |
| `mcp_pass_ms` | MCP 路径通过的时间戳 |
| `last_fail_reason` | 上次失败原因 |

**自动过期检测**：`verification_summary`（`list_packs` 附带回传）会比对"通过时的 Science 版本 / 路径常量" vs "当前"。任一不同 → `stale=true` + `stale_reasons`，桌面面板的验证区顶部弹"⚠ 验证结果可能过期，建议重跑 canary"。这样 Science 更新导致 MCP/Skill 路径变化时，用户会被主动提醒，而不是默默失效。

## 如何贡献一条 verified fact

如果你在 Science 二进制或运行时观察到本清单某条的实际值：

1. 编辑本文件，把状态改为 `V`，在"证据"列贴上 `findings/<记录名>.md` 的链接。
2. 若与现值冲突，同时改 `packs.rs` 的常量或 `bio-*` pack 的实现，跑本项目回归测试。
3. `git commit -s -m "verify(bio-unknowns): confirm <fact>"`。
