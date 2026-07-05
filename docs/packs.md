# 科研工具包（bio-* pack）

CSSwitch 的 pack 机制把一组本地 MCP server + Skill 打包成一个 checkbox。适合把**同一域的一组工具**捆绑分发（例如生物医学文献检索）。

## 为什么必须是本地 MCP

Claude Science 的远程 MCP（`*.mcp.claude.com` 上的 pubmed / chembl / ct.gov / biorxiv）需要真实 Anthropic 授权。CSSwitch 走**虚拟登录**，代理已经把这些远程 MCP fast-fail 掉了（`README.md:101`）。所以要在虚拟登录下用这些数据源，只能走本地 MCP，直接打各自的公开 API。

## 布局

```
packs/
  _lib/                 # MCP stdio 框架 + urllib 客户端 + 磁盘缓存（stdlib 唯一依赖）
    server.py, http.py, cache.py, entrez.py
  bio-lit/              # PubMed / EuropePMC / Crossref / bioRxiv / medRxiv
  bio-audit/            # 引用校验 + 证据类型分类 + 证据表 + Skill 强制规范
    skills/evidence-audit/SKILL.md
  bio-trials/           # ClinicalTrials.gov v2
  bio-gene/             # NCBI Gene/ClinVar/dbSNP/GEO/SRA + UniProt + Ensembl
  bio-drug/             # ChEMBL + Open Targets + RxNorm + openFDA
  bio-compiler/         # 研究问题编译器：模糊问题 → 结构化研究任务书 + 工具链路由

  <pack>/pack.json      # 每个 pack 的 manifest
```

`pack.json` schema：

```json
{
  "id": "bio-lit",
  "name": "生物医学文献检索",
  "description": "…",
  "version": "0.1.0",
  "requires_env": [],                      // 必填环境变量；缺则 UI 显示"缺 X"、跳过装配
  "optional_env": [                        // 可选环境变量；UI 里给输入框
    {"name": "NCBI_API_KEY", "label": "…", "url": "https://…"}
  ],
  "depends_on": ["bio-lit"],               // 建议一起启用的兄弟 pack（UI 只 chip 提示，不硬拦）
  "servers": [
    {"name": "bio-lit-pubmed",             // MCP server 名。**必须以 `bio-` 前缀**，
     "script": "packs/bio-lit/pubmed_server.py",  // 后端凭前缀识别本项目管理的 server
     "env_pass": ["NCBI_API_KEY", "NCBI_EMAIL"]}  // 白名单：只有这里点名的变量才注入 MCP env
  ],
  "skills": [
    {"id": "evidence-audit", "src": "packs/bio-audit/skills/evidence-audit"}
  ]
}
```

## 装配流程

1. 桌面面板勾选 pack → Tauri command `toggle_pack(id, enabled)` 落盘 `~/.csswitch/config.json` 的 `enabled_packs`。
2. 若沙箱在跑，`packs::apply` 把当前启用集合 merge 进 `<SANDBOX_HOME>/.claude-science/mcp-servers.json`，Skill 拷进 `<SANDBOX_HOME>/.claude-science/skills/<skill-id>/`。
3. Claude Science 只在**启动时**读一次 MCP 配置，所以 apply 后后端会停沙箱、UI 提示用户再点「一键开始」。
4. 一键开始时的 `one_click_login` 会在 launch Science **之前**再跑一次 `packs::apply`，保证首次启动就把配置准备好。

## 铁律相关

- `packs::apply` 只写 `<SANDBOX_HOME>/.claude-science/`，绝不碰真实 `~/.claude-science`。
- 前后官方模式切换：`set_mode("official")` 会调 `packs::purge_bio_from_mcp` 把本项目管理的 `bio-*` server 从 MCP 配置里拆干净（保留用户手工添加的其它 server）。
- 环境变量（NCBI_API_KEY 等）走 `config.pack_env`（0600 明文存盘），env 注入 MCP 子进程时**只透传 `env_pass` 白名单里的名字**，防止把无关的 provider key 也带出去。
- pack 的 Python 脚本以子进程方式由 Claude Science spawn；CSSwitch 不直接持有这些子进程，进程生命周期跟着沙箱走。

## 仍需要人工核对的点（TODO）

1. **Claude Science 的 MCP 配置文件位置和 schema 尚未逆向确认**。当前按 Claude Code 惯例落在 `<data-dir>/mcp-servers.json`（`packs::MCP_CONFIG_REL`），schema `{"mcpServers": {"<name>": {"command", "args", "env"}}}`。
   核对方法：手工在沙箱 Science 里加一个 MCP（如果 UI 支持），看它把配置写到哪。或 `strings claude-science | grep -i mcp` 找路径常量。
2. **Skill 目录位置同样未逆向确认**。当前落在 `<data-dir>/skills/<id>/SKILL.md`（`packs::SKILLS_REL`）。核对方法：看 tools 清单里的 `search_skills` / `skill` 的调用参数是怎么定位 skill 的。
3. 上述两条如果错，只改 `packs.rs` 顶部两个常量 + `write_mcp_config` 里的 key 名即可，UI 和 Python 侧无感。

## 加一个新 pack

1. 建 `packs/<pack-id>/pack.json`（id 前缀不硬性要求，但 server name **必须 `bio-` 起头**——凭这个前缀分辨归属，避免踩用户自加的其它 MCP）。
2. 每个 server 一个 Python 文件，`#!/usr/bin/env python3`，`if __name__ == "__main__": server.run()`。
3. tool 定义用 `@server.tool(name, description, input_schema)` 装饰；返回 str / list（MCP content） / 任意可 JSON 化对象。
4. 若需要 Skill，写 `SKILL.md`（必须首行是 `---` frontmatter 段，含 `name:` `description:`），放在 `pack/skills/<skill-id>/SKILL.md`。
5. 不需要在任何地方注册 pack —— `packs::list_packs` 会自动扫 `packs/*/pack.json`。

## 实体标准化（bio-norm）

覆盖生物医学最容易踩的歧义坑：
- HGNC — 基因 / 蛋白正名（含 previous symbol / alias / entrez / ensembl / uniprot 交叉）
- OLS4（EBI）— MONDO / DOID（疾病）、HPO（表型）、GO（通路 / 功能）、ChEBI（化学），一个 API 覆盖 5 个本体
- MeSH — 医学主题词（tree number / entry terms）
- `disambiguate(term, context)` 是招牌：并行打 HGNC + MeSH + OLS，用 context 做 Jaccard 重叠加权，返回排序候选。举例："APC" + context 里出现 "colon polyp" → APC gene 第一；context 出现 "immune synapse" → antigen-presenting cell 第一。

评分是**可解释**的启发式（label 精确匹配 +0.5、HGNC 精确 symbol +0.5、context Jaccard × 0.4），不搞黑盒模型 — 便于用户/上游 LLM 自己判断"top-1 是不是够可信"。

## 工作流模板（bio-workflows）

6 个 Skill 预设，靠触发词自动进入对应科研模式，组合复用其它 pack 的 MCP：

| Skill | 场景 | 触发关键词示例 |
|---|---|---|
| `lit-review` | 文献综述 / SR | 帮我做综述、systematic review、meta-analysis |
| `target-discovery` | 靶点发现 / 老药新用 | drug repurposing、这个疾病有什么靶点 |
| `geo-triage` | 公共转录组数据初筛 | GEO 数据集、DEG 分析、GSEA |
| `trial-landscape` | 临床试验管线情报 | pipeline analysis、endpoint benchmark |
| `reviewer-response` | 审稿意见回复 | rebuttal、R1、修回信 |
| `grant-specific-aims` | 基金 Aims 页 | R01 aims、NSFC、写标书 |
| `uncertainty-first` | **横切收尾标准** | 所有工作流结论阶段共用（见下） |

每个 Skill 都写了"触发后先问 X 件事"、Do/Don't、以及**反例**（示范一种典型的错误答复），让 LLM 有明确的边界感。

### 不确定性优先（uncertainty-first，横切标准）

研究者最需要的不是"告诉我已知的"，而是**帮我看见盲区**。所以每个 workflow 的结论阶段都**强制**输出五段不确定性面板：**Known knowns / Known unknowns / Conflicts / Missing data / Next experiment**。6 个 workflow skill 结尾都加了这条硬约束，另有一个专门的 `uncertainty-first` skill 定义标准与反例。

生成方式不是纯手写：先把结论拆 claim 走 `evidence_graph`，再把结果喂 `uncertainty_ledger`（bio-audit MCP），它自动派生大部分条目（supported→known knowns 带边界；unsupported→known unknowns；graph 冲突/反证→conflicts；窄边界→missing data；并给 next-experiment 候选），模型只补工具挖不到的领域先验。

## 研究问题编译器（bio-compiler）

把模糊问题（"EGFR 在 GBM 里还有没有新靶点价值"）**编译**成结构化研究任务书，再开搜。招牌工具 `compile_research_question`：

- **识别实体**：疾病缩写表（GBM→Glioblastoma+MONDO 提示）/ 中文别名 / 已知靶点集（EGFR…）/ 药物后缀（-nib/-mab…）。识别不到的标 `candidate` / `needs_user_input`，**绝不编**。
- **识别原型**：靶点验证 / 老药新用 / 生物标志物 / 机制 / 疗效比较 / 流行病学 / 安全性 —— 决定终点、数据库、证据门槛、该进哪个 workflow skill。
- **产出任务书**：研究对象 · 疾病 · 分子 · 干预 · 终点 · 数据库 · 排除标准 · 证据等级门槛 · 推荐工具链 · 推荐 skill · `gaps`（待用户回填）。每个字段带 `via`（凭哪条规则得到），可核对。

配套 `question-compiler` skill 强制"先编译、缺口回填、再检索"；结论阶段仍走 evidence_graph + uncertainty_ledger。`compiler_capabilities` 工具自述当前覆盖范围（透明度）。

## 隐私 / 合规（bio-privacy）

三层配合：
- **PHI 扫描 / 脱敏**（`phi_server.py`）：纯正则，本地跑，覆盖 HIPAA Safe Harbor 里能可靠检测的字段（日期 / 电话 / SSN / 中国身份证号 / MRN / 邮编 / 邮箱 / URL / IP / 高龄 / 姓名启发式）。返回带 confidence 的 findings；`phi_redact` 用一致占位符（`[PATIENT_1]`）替换，同一原始字符串永远对应同一 token，便于本地审阅。
- **审计日志**（`audit_server.py`）：追加式 JSON-Lines，`~/.csswitch/audit/YYYY-MM-DD.jsonl`（0600）。工具**只吃 hash + 摘要**，`input_sample` 参数会被 SHA-256 后丢弃 —— 审计日志本身能给第三方看。
- **敏感模式门**（后端 Rust）：`sensitive_mode=true` 时，`one_click_login` 拒绝把请求发给不在 `local_endpoint_hosts` 白名单里的 provider。白名单**反向防御**：`api.deepseek.com` / `dashscope.aliyuncs.com` / `api.anthropic.com` / `openai.com` 一律拒绝加入（否则等于绕过敏感模式）。
- Skill `sensitive-mode`：在识别到疑似临床数据时**先扫再问**，给用户 A/撤回、B/脱敏后继续、C/本地端点 三选一。**不代替用户决定**。

## 远程 MCP 本地替身层（bio-mcp-shim）

虚拟登录下 `*.mcp.claude.com` 的远程 pubmed / clinical-trials / chembl / biorxiv 被代理 fast-fail。**bio-mcp-shim** 让沙箱工具列表**仍然看到同名 MCP**，流量走本地 API + 用户填的 key。

技术上靠 `ServerDef.aliases`：一个本地 MCP 以多个名字挂进 mcp-servers.json。开启后 Science 里同时看到 `bio-mcp-shim-pubmed`（本项目命名）和 `pubmed`（Anthropic 兼容名）。用户提示词 / SKILL 里出现 `search_articles` / `search_trials` / `compound_search` 这些远程 MCP 惯用工具名时不会失配。

**工具名对齐**：pubmed → `search_articles / get_article_metadata / get_full_text_article / find_related_articles / convert_article_ids / get_copyright_status / lookup_article_by_citation`；clinical-trials → `search_trials / get_trial_details / search_by_sponsor / search_investigators / analyze_endpoints / search_by_eligibility`；chembl → `compound_search / target_search / get_bioactivity / get_mechanism / drug_search / get_admet`；biorxiv → `search_preprints / get_preprint / get_categories / search_published_preprints / funder_search / get_statistics`。

**冲突处理**：若用户已手工把同名 MCP 挂进沙箱，`packs::apply` 保留原有的、跳过 alias 注册，并在 warnings 里报告；本项目自己的 `bio-mcp-shim-*` server 仍装配，用户可以用长名字调。

## 任务级模型路由

`config.task_routes`（task_id → profile_id）+ `config.probe_results`（探针快照）驱动"生医任务 → profile 路由"折叠区。

- **内置任务清单**：`packs::BIOMED_TASKS`（lit-review / clinical-trials / target-discovery / omics-code / long-context-pdf / tool-heavy / evidence-check / phi-sensitive），随代码走，不能新增/删除（与 Skill 触发词耦合）。
- **`run_probes` 命令**：面板一键跑三条 micro 探针（tool_use / long_ctx / json_stable），结果写回 `probe_results`（key: `<profile_id>:<probe>`）。
- **`test/bio_eval/`**：9 类 ~49 case 的多维 benchmark。`python test/bio_eval/run.py --proxy ... --write-to-config` 会把 per-category 得分（bio_eval_lit_review / bio_eval_clinical_trials / bio_eval_evidence_audit / ...）写回 `probe_results` 作为 rich 结果。

### 探针评断规则（可解释）

- `tool_use`：一发带 `tools=[echo]` + `tool_choice="tool"` 的最小请求，看响应是否含 `tool_use` block。三档：`ok / degraded / fail`。`degraded` 通常意味着"200 但工具被降级成文本"（DSML 泄漏这类）。
- `long_ctx`：32 KiB payload，看是否 200 通过或 400 拒绝。
- `json_stable`：要求返回严格 JSON schema，看能否稳定输出可解析 JSON。

## 生医回归测试 / Benchmark（`test/bio_eval/`）

**9 大类**（文献综述 / 临床试验 / 靶点发现 / 药物再利用 / 组学分析 / 证据审计 / PHI 处理 / JSON 稳定性 / 多轮工具调用），当前 ~49 个可运行 seed case，框架支持扩到每类 20–50（见 `test/bio_eval/README.md` 的扩充路线）。

评分**不再只看"有没有调工具"**。`rubric.py` 多维打分：`tool_invoked`（该调的调了没，`gate` 维度不过封顶 0.4）· `query_relevance`（检索参数对不对题）· **`grounded`（答复里的 ID 是否真来自工具结果，不是编的）** · **`uncertainty`（是否输出五段面板）** · `json_valid` · `custom`（PHI 不泄漏 / 多轮轮数 / 审计 verdict 被引用）。外加编 ID 的乘法惩罚（全编归零；反幻觉 case 用 `expected_fake_ids` 排除"故意埋的假 ID"）。

```
python test/bio_eval/run.py --proxy http://127.0.0.1:18991/<secret> --label deepseek-v4-pro
python test/bio_eval/run.py --list        # 列出全部 case（不打上游）
python test/bio_eval/run.py --selftest    # 离线自检 rubric（CI 用，不打上游）
python test/bio_eval/run.py --summary     # 汇总所有 profile 历史
```

阈值：`✓✓ ≥ 0.9`（强推荐）· `✓ ≥ 0.7` · `⚠ ≥ 0.4`（可用但避开对应场景）· `✗ < 0.4`（不建议）。`test/test_bio_offline.py` 已把 evidence_profile / evidence_graph / 编译器 / rubric 自检纳入离线 CI。

## 证据审计（bio-audit）

`bio-audit` 是 pack 机制的"重点用户"，用来展示"MCP + Skill 两层配合"的效果：

- MCP `evidence_verify` 强校验每个 PMID/DOI/NCT 真实存在，返回归一化元数据 + 证据类型 + 物种/来源警告。
- Skill `evidence-audit` 用触发词覆盖所有医学问答场景，强制模型答复前必须调 `evidence_verify` 过一遍，未通过的引用必须撤回或明示"未核实"。

**这两层一起才防幻觉**：单靠 Skill 约束模型很容易被绕过；单靠 MCP 校验，模型可能压根不调工具就直接编 PMID。Skill 强制了"必须调"，MCP 强制了"编的就穿帮"。

### Claim 级证据图（evidence_graph / evidence_profile）

`evidence_verify` 只回答"引用真不真"。需要**适用边界**和**反证**时升级到 claim 级证据图：

- `evidence_profile(id_type, id)` —— 单篇深挖：**物种 / 人群（年龄性别）/ 样本量 / 实验类型（临床 II 期 · 动物 · 体外 · 回顾性队列）/ 疾病阶段**。抽取靠 `_lib/evidence_profile.py` 的可解释启发式：物种优先信 MeSH CheckTag，样本量正则挖摘要，方向（回顾/前瞻）看 MeSH——每个推断都返回 `signals`（凭哪条 MeSH / 摘要片段得到），不是黑盒。
- `evidence_graph(claims)` —— 把每条 claim 绑证据后算出：① 证据等级 ② **适用边界**（物种/人群/阶段/样本量）③ **conflicts**（含"断言人类但证据是动物"的错配、方向相反的反证）④ **counter_evidence**（`stance:"refutes"` 标注的反例）。返回机器可读 nodes/edges + 每条 claim 的 verdict（supported/contested/unsupported）。

结论最终落成需求要的形态："结论 A 由 PMID1/PMID2/NCT3 支持，证据等级为临床 II 期 / 动物 / 体外 / 回顾性队列，适用边界是 X，反例在 PMID4"。再把 `graph.claims` 喂 `uncertainty_ledger` 产出五段面板。
