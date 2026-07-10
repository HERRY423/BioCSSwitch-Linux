# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 铁律（最高优先级，任何会话不得违反）

1. **绝不复制/修改/删除真实 `~/.claude-science`**（含 `.oauth-tokens`/`encryption.key`/`active-org.json`/`orgs/`/`.key-backups/`）。只读都要谨慎。
2. **绝不把真实 OAuth token 复制进沙箱。** 沙箱只用自己的本地虚拟令牌（Rust 原生 `oauth_forge.rs` 生成）。
3. **绝不碰真实端口 8765。** 所有沙箱用独立 HOME + 独立端口 + 独立 data-dir。
4. **测试默认不碰 Science。** 能用代理↔上游单独验证的，不启动 Science。整链冒烟须用户明确同意且在在场。
5. **用户可见文案脱敏。** 主按钮用「一键开始」等中性说法；技术内部文档描述机制时可仍用「虚拟登录」/「越过头票」。

## 项目身份

BioCSSwitch = 上游 [CSSwitch](https://github.com/SuperJJ007/CSSwitch)（Claude Science 本地模型切换器）+ 19 个生物医学本地 MCP/Skill pack。定位是 **AI 生物医学研究平台**，不作为模型切换器呈现——研究者先选择要完成的工作，模型连接是底层设置。

- 仓库：`HERRY423/BioCSSwitch`，MIT 许可
- 当前版本：**v0.4.0**（tag `bio-v0.4.0`）
- 平台：macOS Apple Silicon（arm64），未公证
- 语言：Python 75% / Rust 16% / JavaScript 4% / Shell 2%

## 分层架构（三层）

```
┌─ 桌面 App（Tauri 2，正常窗口 420×700）──────────────┐
│  Rust 后端：进程管家（起停代理/沙箱、读写配置、探活、切换事务） │
│  JS 前端：原生 HTML/CSS/JS（main.js ~70KB，无框架）     │
│  虚拟 OAuth 伪造：Rust 原生（oauth_forge.rs，零外部运行时） │
├─ 翻译代理（Python，httpx + h2，HTTP/2 连接池）───────────┤
│  入站：剥离 Science 的 OAuth Bearer + path-secret 鉴权   │
│  出站：按 adapter 注入第三方 key + 协议转换（如需）       │
│  6 模块拆分（v0.4.0）：request_context / http_transport /│
│    provider_registry / provider_policy / anthropic_compat│
│    / fallback_policy + 独立模块：dsml_shim / task_router │
│    / ultra_orchestrator / debate_arena / knowledge_ingest│
├─ 生物医学 Pack 系统（19 个 pack，本地 MCP + Skill）───────│
│  Python MCP stdio 服务器（_lib/server.py 轻量框架）       │
│  覆盖：文献/试验/药物/基因/单细胞/scFM/空间/ML/审计/隐私  │
│  证据链：evidence_verify → evidence_graph → GRADE →     │
│          uncertainty_ledger → 五段不确定性面板            │
└──────────────────────────────────────────────────────┘
```

## 命令速查

### 代理（Python）

```bash
# 起代理（默认 DeepSeek，原生 Anthropic 透传）
DEEPSEEK_API_KEY=... python3 proxy/csswitch_proxy.py --provider deepseek --port 18991

# 切千问（唯一需要 Anthropic↔OpenAI 翻译的 provider）
DASHSCOPE_API_KEY=... python3 proxy/csswitch_proxy.py --provider qwen --port 18991

# relay（Anthropic 兼容透传，双鉴权）
CSSWITCH_RELAY_BASE_URL=https://open.bigmodel.cn/api/anthropic CSSWITCH_RELAY_KEY=<key> \
  CSSWITCH_RELAY_MODEL=glm-5.2 python3 proxy/csswitch_proxy.py --provider relay --port 18996

# 也支持 --env-file 从文件读 key；--auth-token 设 path-secret
```

### 桌面 App（Tauri）

```bash
cd desktop
npm install                    # 首次：装 Tauri CLI（构建时需要 node，运行时不需要）
npm run tauri dev              # 开发跑（正常窗口）
npm run tauri build            # 打包 → .dmg（macOS arm64）
```

**Windows 主开发机不发版**：推送 tag 后由 GitHub Actions (`macos-package.yml`, `macos-15` runner) 自动构建 `.dmg`。在该 tag 上手动运行 workflow 并勾选 `publish_release` 即可挂到 Release。

### 测试

```bash
# 全量离线回归（不碰 Science、不联网）
bash test/run_all.sh

# Python 代理单测（40）
python3 -m pip install -e ".[dev]"
python3 -m pytest test/test_proxy_units.py

# 生物医学离线测试（62+ 断言：GRADE 引擎/scFM provenance/编译器/隐私/红队）
python test/test_bio_offline.py

# Rust 后端测试（122）
cd desktop/src-tauri && cargo test

# Rust lint + format
cargo clippy --all-targets -- -D warnings && cargo fmt --check

# 前端语法（无测试框架，逻辑手动验证）
node --check desktop/src/main.js

# 生医 benchmark 离线自检（CI 用，不打上游）
python test/bio_eval/run.py --selftest
```

### 生医 Benchmark（bio_eval，打上游 = 花钱）

```bash
# 跑全部 16 类 70+ case（需要代理在跑、profile 已激活）
python test/bio_eval/run.py --proxy http://127.0.0.1:18991/<secret> --label deepseek

# 只跑某几类
python test/bio_eval/run.py --proxy ... --cases safety_redteam,privacy_redteam

# 跑多次测稳定性 + provider 对比矩阵
python test/bio_eval/run.py --proxy ... --repeat 3
python test/bio_eval/run.py --matrix          # 汇总所有 profile

# 列出全部 case（不打上游）/ 离线自检
python test/bio_eval/run.py --list
python test/bio_eval/run.py --selftest
```

## 核心架构

### 模型路由：adapter 分型

所有 provider 经 `desktop/src-tauri/src/templates.rs` 的 `TEMPLATES` 注册表（单一来源）派生出 adapter：

| adapter | 走的 provider | 代理行为 | 协议 |
|:---|:---|:---|:---|
| `deepseek` | DeepSeek | 原生透传 + 模型名映射 + thinking 归一化 | Anthropic |
| `qwen` | 通义千问 | Anthropic↔OpenAI 双向翻译（含 tool_use/SSE） | OpenAI 兼容 |
| `relay` | GLM/Kimi/MiniMax/MiMo/硅基/OpenRouter/自定义 | 原生透传 + force 模型 + 双鉴权 | Anthropic 兼容 |
| `openai-custom` | 自定义 OpenAI | 同 qwen 翻译链，代理拼 `/chat/completions` + `/models` | OpenAI 兼容 |
| `openai-responses` | 自定义 OpenAI Responses | 代理拼 `/responses` + `/models` | OpenAI Responses |

native（deepseek/qwen）走 `--provider` + 各自固定端点；relay 走 `CSSWITCH_RELAY_*` 环境变量。

### 代理模块拆分（v0.4.0）

原单体 `csswitch_proxy.py` 拆为：

| 模块 | 职责 |
|:---|:---|
| `request_context.py` | `RequestContext`：入站请求解析、path-secret 鉴权、header 剥离 |
| `http_transport.py` | 共享 `httpx` 客户端（连接池 + HTTP/2）+ 重试 + `UpstreamHTTPError` |
| `provider_registry.py` | `PROVIDERS` 字典：每家 adapter 的端点/key_env/模型映射/thinking 策略 |
| `provider_policy.py` | 选 provider 的策略门（结合 task_router 路由结果） |
| `anthropic_compat.py` | Anthropic 兼容层的入站/出站处理 |
| `fallback_policy.py` | fallback 策略（主 provider 失败时的降级链） |

独立模块（不参与主请求路径，按需加载）：
- `dsml_shim.py`：DeepSeek DSML 泄漏兜底（`<｜｜DSML｜｜>` tool_use 错吐成文本时截断，默认关）
- `task_router.py`：关键词 → 生医任务路由（crossmodal-discovery / hypothesis-generation / lit-review 等），读 `config.task_routes` + `probe_results`
- `ultra_orchestrator.py`：多步编排（`CSSWITCH_ULTRA_MODE` 环境变量门控，默认关）
- `debate_arena.py`：多模型辩论对抗（科学争议场景）
- `knowledge_ingest.py`：知识摄入（会话结果 → 本地 KG）

### Tauri 后端模块（`desktop/src-tauri/src/`）

| 模块 | 职责 |
|:---|:---|
| `lib.rs` | Tauri command 入口：起停代理/沙箱、注入 env、切换事务、一键开始、状态灯 |
| `config.rs` | `~/.csswitch/config.json` 读写：dir 0700/file 0600、拒符号链接、原子写、key 掩码、schema v2、v1→v2 迁移 |
| `config_legacy.rs` | v1 固定槽结构，仅迁移用 |
| `templates.rs` | provider 模板注册表（单一来源）：adapter/是否必选模型/内置模型/thinking 策略/icon |
| `lifecycle.rs` | 串行器（切换事务加锁）+ generation token |
| `scratch.rs` | 候选连接临时代理探测（Models/Message），起完即杀，不碰正式链路 |
| `oauth_forge.rs` | Rust 原生虚拟 OAuth 伪造（HKDF-SHA256 + AES-256-GCM v2；护栏拒真实目录） |
| `packs.rs` | Pack 装配引擎：扫描 `packs/*/pack.json` → 校验 schema → 拓扑排序依赖 → 写 MCP 配置 + 拷 Skill 到沙箱 |
| `proc.rs` | 纯 std：TCP `/health` 探活（带 path-secret）、which、`/dev/urandom` secret、上游可达性 |
| `state.rs` | `AppState`：Mutex 保护代理/沙箱子进程 + 指纹比对 |
| `verification.rs` | Key 校验守卫 |

**前后端契约关键点**：Tauri 顶层多词 command 参数用 **camelCase**（`templateId`/`baseUrl`/`skipVerify`），serde struct 入参内部字段仍 snake_case。Key 完整值永不进前端，只回显掩码末 4 位。

### 生物医学 Pack 系统

```
packs/
  pack.schema.json        # 所有 pack.json 的 JSON Schema（v0.4.0）
  __init__.py             # 包命名空间
  _lib/                   # 共享框架（12 模块，零 pip 依赖）
    server.py             # 最小 MCP stdio 服务器（JSON-RPC 2.0，协议 2024-11-05）
    http.py               # urllib 客户端 + 磁盘缓存
    cache.py              # 请求缓存层
    entrez.py             # NCBI Entrez API 封装
    provenance.py         # 规范化 JSON + sha256 内容哈希（可复现性追溯）
    evidence_profile.py   # 证据深挖：物种/人群/样本量/实验类型（可解释启发式）
    extrapolation_checker.py / methodology_checker.py / critique_scoring.py
    counter_experiment.py # 证伪实验设计
    fixtures.py           # 离线 fixture 录制/回放（自动脱敏 API key）
  bio-lit/                # PubMed / EuropePMC / Crossref / bioRxiv / medRxiv
  bio-audit/              # 引用校验 + 证据类型分类 + GRADE/SoF 引擎 + 不确定性账本
  bio-trials/             # ClinicalTrials.gov v2
  bio-gene/               # NCBI Gene/ClinVar/dbSNP/GEO/SRA + UniProt + Ensembl
  bio-drug/               # ChEMBL + Open Targets + RxNorm + openFDA
  bio-norm/               # 实体标准化：HGNC / OLS4( MONDO/DOID/HPO/GO/ChEBI ) / MeSH + disambiguate
  bio-compiler/           # 研究问题编译器：模糊问题 → 结构化任务书 + 工具链路由
  bio-workflows/          # 7 个 Skill 预设：lit-review / target-discovery / geo-triage / trial-landscape / reviewer-response / grant-specific-aims / uncertainty-first
  bio-privacy/            # PHI 扫描/脱敏 + 审计日志 + 敏感模式门
  bio-singlecell/         # 单细胞预处理（AnnData 指纹/QC/doublet/batch/cell-type recipe）
  bio-scfm/               # Geneformer/scGPT/CellFM/UCE embedding skeleton + provenance
  bio-sc-downstream/      # DEG / trajectory / cell communication / marker / enrichment 配方
  bio-sc-atlas/           # CELLxGENE 检索与下载 skeleton
  bio-spatial/            # 空间转录组 / H&E-to-ST / 3D atlas recipe
  bio-ml/                 # 多模态 FM / virtual cell / federated learning / validation gate
  bio-kg/                 # 因果知识图谱（JSONL）+ 冲突检测 + 矛盾驱动假设生成
  bio-crossmodal/         # 15 步 DAG 跨 6 模态编排（文献/基因/药物/试验/单细胞/空间）
  bio-research-partner/   # 隐私优先的本地兴趣模型（HMAC-SHA256 伪名化 + 显式 opt-in）
  bio-experiment/         # 实验设计：竞争假设 + 区分性实验 + 对照
  bio-critique/           # 科学批判：9 个工具（含 design_counter_experiment / critique_checklist）
  bio-mcp-shim/           # 远程 MCP 本地替身（让 pubmed/clinical-trials/chembl/biorxiv 同名可用）
```

**装配流程**：
1. 桌面面板勾选 pack → `toggle_pack(id, enabled)` 落盘 `enabled_packs`
2. `packs::apply` 把启用集合 merge 进 `<SANDBOX_HOME>/.claude-science/mcp-servers.json`，Skill 拷进 `<SANDBOX_HOME>/.claude-science/skills/<id>/`
3. 一键开始时 `one_click_login` 在 launch Science 前再跑一次 `packs::apply`

**关键约束**：
- Server name 必须 `bio-` 前缀（凭此前缀分辨归属）
- MCP 配置文件位置 `mcp-servers.json` 与 Skill 目录 `skills/` 的路径**尚未从 Science 二进制逆向确认**（见 `packs.rs` 的 TODO(verify)），按 Claude Code 惯例假设
- `packs::apply` 只写沙箱目录，绝不碰真实 `~/.claude-science`
- 官方模式切回时 `packs::purge_bio_from_mcp` 拆干净 `bio-*` server

### Pack Skill 五段不确定性面板（强制标准）

所有 bio-workflow skill 的结论阶段强制输出（由 `uncertainty_ledger` 工具自动派生）：
- **Known knowns** / **Known unknowns** / **Conflicts** / **Missing data** / **Next experiment**
- v0.4.0 已修复 `language` 参数：zh/en 双语贯通（此前硬编码中文）

### 证据审计链（三层递进）

```
evidence_verify(id_type, id)           → 引用真不真（PMID/DOI/NCT 校验）
evidence_profile(id_type, id)          → 物种/人群/样本量/实验类型/疾病阶段
evidence_graph(claims)                 → 每 claim 绑证据 → verdict + 适用边界 + 反证
grade_outcome(...)                     → GRADE 确定性评级（四档 ⊕⊕⊕⊕/⊕⊕⊕⊝/⊕⊕⊝⊝/⊕⊝⊝⊝）
grade_evidence_dossier(...)            → 结构化证据档案（跨 study body-of-evidence）
grade_sof_table(...)                   → Summary of Findings 表
etd_recommendation / etd_probabilistic → 证据→决策框架
uncertainty_ledger(evidence_graph)     → 五段面板
```

关键设计原则：**工具定死算术、模型给判断**——模型无法含糊说"中等确定性"，必须逐域声明为什么。

## 前端代码组织（`desktop/src/`）

- `index.html`：单一 HTML 页面，420×700 窗口
- `styles.css`：全部样式（~11KB）
- `main.js`：全部逻辑（~70KB，原生 JS，无框架）。核心概念：
  - `config` 全局变量：缓存 `get_config` 返回值（profiles/templates/active_id/mode/pending_notice）
  - `renderProfiles()`：列表渲染 + chip 网格 + 三能力模型呈现（native/relay/custom）
  - `setBusy(true/false)`：防连点，置灰主按钮
  - 所有 Tauri command 调用通过 `invoke('command_name', {camelCase: value})`
- `ui-logic.js`：可测试的纯 UI 函数（`maskKey`/`filterModels`/`statusLabel`），配套 `ui-logic.test.js`

## 关键数据流

### 一键开始（`one_click_login`）

```
用户点「一键开始」
  → setBusy(true)
  → ensure_proxy（幂等：端口/provider/key 指纹一致且健康就复用）
  → ensure_virtual_login（org_uuid 只在真首启铸一次，此后 sticky；保 org 不丢旧对话）
  → launch_sandbox（起沙箱 Science，指向代理 + path-secret）
  → 返回 Science URL → 浏览器打开
```

### 切换 profile（`set_active_profile`，经串行器）

```
1. scratch 校验候选（起临时代理→打 Models/Message 探测→健康才继续）
2. 起正式代理（带新 key）
3. 探活健康才提交 active_id
4. 失败→杀候选→恢复旧代理→不停沙箱
5. 返回 generation token（防过期写入）
```

## Provider 接入方式速查

| 来源 | adapter | 鉴权头 | 模型选择 |
|:---|:---|:---|:---|
| DeepSeek | deepseek | `x-api-key` | 内置映射：`claude-opus-4-8→deepseek-v4-pro` |
| 通义千问 | qwen | `Authorization: Bearer` | DashScope 兼容端点，翻译链 |
| 智谱 GLM | relay | 双鉴权（`Authorization` + `x-api-key`） | force override |
| Kimi/MiniMax/MiMo/硅基/OpenRouter | relay | 同上 | force override，各家 thinking 策略不同 |
| 自定义 Anthropic | relay | 自填 base_url | 自填模型名 |
| 自定义 OpenAI | openai-custom | `Authorization: Bearer` | 自填 base_url，代理拼 `/chat/completions` |

**模型选择器借壳机制**（Science 二进制硬规则：模型 id 必须 `claude-` 开头，且 `^claude-(opus|sonnet|haiku)-<数字>$` 才进主列表）：代理 force 模式时 `/v1/models` 返回单壳 `claude-opus-4-8` + `display_name="真实模型名"`，出站 `model_map` 还原真实 id。详见 `docs/verified-facts.md` 事实 6。

## 安全边界

- API Key：`~/.csswitch/config.json`（0600），环境变量注入子进程，不进 argv；前端只回显掩码末 4 位
- 代理：仅监听 `127.0.0.1`，path-secret 鉴权（16 字节 hex token）
- 入站 `Authorization` / `x-api-key` 一律剥离后丢弃
- 沙箱：独立 HOME、独立端口、独立 data-dir（`~/.csswitch/sandbox/home/`）
- 代码扫描：CI 跑 gitleaks（含完整历史）+ cargo audit + pip-audit
- 无自动遥测/崩溃上报

## 目录与关键文件索引

| 路径 | 内容 |
|:---|:---|
| `proxy/csswitch_proxy.py` | 主代理入口（~1400 行，6 模块协调） |
| `desktop/src-tauri/src/lib.rs` | Rust 后端入口（~1500 行） |
| `desktop/src/main.js` | 前端面板逻辑（~70KB） |
| `desktop/src-tauri/src/templates.rs` | provider 模板注册表 |
| `desktop/src-tauri/src/config.rs` | 配置读写 + schema 迁移 |
| `desktop/src-tauri/src/packs.rs` | Pack 装配引擎 |
| `desktop/src-tauri/src/oauth_forge.rs` | 虚拟 OAuth 伪造 |
| `packs/_lib/server.py` | MCP stdio 框架 |
| `packs/pack.schema.json` | Pack manifest schema |
| `packs/SKILLS_AUDIT.md` | 21 skills × 169 tools 交叉审计 |
| `docs/verified-facts.md` | 逆向记录与已验证事实（Science 二进制分析） |
| `docs/known-issues.md` | 待修队列与排期 |
| `docs/packs.md` | Pack 系统完整文档 |
| `docs/research-partner-crossmodal.md` | 研究伙伴 + 跨模态编排架构 |
| `docs/DEVELOPMENT.md` | 开发交接文档（构建/测试/整链冒烟/发版流程） |
| `docs/provider-support.md` | Provider 支持调研（封存） |
| `docs/dependency-analysis.md` | 运行时依赖分析（node-ectomy 已完成，剩 python-ectomy） |
| `docs/proposals/` | 设计提案（bioinformatics-expansion / critique-engine / ultra-subagent 等） |
| `docs/releases/` | 各版本发布说明 |
| `test/bio_eval/` | 生医 benchmark 框架（16 类 70+ case，多维 rubric） |
| `test/test_bio_offline.py` | 生物医学离线 CI 测试 |
| `test/test_proxy_units.py` | 代理纯逻辑单测（40） |
| `scripts/launch-virtual-sandbox.sh` | 起沙箱 Science（独立 HOME+端口） |
| `scripts/stop-science-sandbox.sh` | 停沙箱（按 data-dir，绝不影响真实 8765） |
| `scripts/make-virtual-oauth.mjs` | 虚拟 OAuth 伪造器（Node 独立版，等价 Rust 实现） |
| `findings/` | 证据/二进制分析/诊断记录；`auto-maint/` 巡检输出（git 忽略） |

## 环境备忘

- 真实 Science 端口 8765，数据目录 `~/.claude-science`——绝不碰
- 代理端口坑：大写 `HTTPS_PROXY`/`HTTP_PROXY`→`127.0.0.1:8001`（死），小写走 `127.0.0.1:7890`。gh（Go）读大写 → 误报 token invalid。跑 gh/git 前：`export HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890 ALL_PROXY=http://127.0.0.1:7890`
- Python 用 conda 环境，避免系统 3.9
- Rust 国内镜像：`RUSTUP_DIST_SERVER=https://rsproxy.cn`，crates.io 走 `sparse+https://rsproxy.cn/index/`
- 代理运行时依赖 `httpx[http2]`（`proxy/requirements-runtime.txt`），发布包经 `scripts/vendor-python-runtime.py` 打入 `python-vendor/`
- 现有 CLAUDE.md 里版本号/发布状态以 `CHANGELOG.md` + `docs/known-issues.md` 为准
