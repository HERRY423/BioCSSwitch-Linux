---
name: sensitive-mode
description: 用于任何**可能含患者数据 / 临床原始记录 / 医疗档案**的场景，强制先做 PHI 检测再决定去向。触发：患者、病历、病案、临床数据、EHR、EMR、住院记录、门诊记录、handover note、progress note、discharge summary、SOAP、真实世界数据、RWD、reidentification、identifiable data、真实病人、我这里有一段病历、这是一份体检报告、帮我看一下这份 CT 报告、我上传一份门诊记录、患者档案、患儿、受试者数据、subject-level data、临床原始表、GCP 数据、eCRF、我要处理 HIPAA、PHI、脱敏、去标识化、我们医院的数据。也在提到 sensitive_mode / 敏感模式 / 隐私模式 时触发。禁用于：公开文献 / 已发表数据 —— 那些不含 PHI，扫描是浪费时间。
---

# 隐私 / 合规模式（sensitive-mode）

**这不是可选流程，是硬门**。任何一进来看起来像临床原始数据的内容，你必须先做完 PHI 扫描才能进入解答阶段。

## 三条铁律

1. **未扫描不作答**。用户贴一段病历、体检报告、handover note，你的第一步是 `phi_scan`，不是解读症状。
2. **未获用户同意不脱敏发送**。扫描出 PHI 后，你**必须问用户**：撤回 / 脱敏后发送 / 换本地端点。不能自作主张替他们决定。
3. **一切都写审计日志**。`phi_scan` 结果、用户的选择、最终发送的模型，全部通过 `audit_log_write` 记一条。审计日志绝不写原文（工具只吃 hash + 摘要）。

## 工作流

### Step 1：接到疑似临床内容

判断信号（任一即触发）：
- 用户明说"这是病历"、"这是患者数据"、"给你看一份 CT 报告"
- 段落里出现姓名 + 年龄 + 日期 + 症状的组合结构（SOAP note / progress note 特征）
- 明确的 identifier：MRN、住院号、就诊号、ID 号
- 用户机构域名（.hospital.cn、mayo.edu、nhs.uk 这类）

**触发条件成立就直接跳 Step 2，不要先"简单看看"**。

### Step 2：先扫

```
调用 phi_scan(text=<用户提供的整段内容>)
```

看返回的 `verdict`：
- `no_phi_detected` → 继续问自己："真的没有吗？"若你**认为**内容涉及临床数据但扫描没抓到，仍要按 PHI 处理（正则会漏检姓名、模糊日期、医院名等）。用户明说是临床数据 = 一律按 PHI 走。
- `phi_possible`（低置信度） → 提示用户"检测到可能是 PHI 的字段，请核对"
- `phi_likely` → 停下来，进入 Step 3

### Step 3：给用户三个选择

严格按下面结构回复（不要加"当然可以帮您分析"这类开场白）：

```
⚠️ 检测到疑似 PHI（HIPAA 保护对象）

    高置信度命中：<N> 条
    可能命中：<M> 条
    类别：<by_kind 摘要>

在继续前，请选择：

A. 撤回这段内容，我改用无 PHI 的描述重发
B. 就地脱敏后继续（我会把姓名/日期/ID 替换成 [PATIENT_1] 这类占位符）
C. 我使用的是本地 / 机构端点（非公开 API），可原文继续
    ↳ 请**明确确认**你当前的 provider 是本地或机构受控端点（如 Ollama、你们医院的 OpenAI 兼容端点、SecureGPT 等）

若不选择，我不会继续这条请求。
```

### Step 4：按用户选择走

**A（撤回）**：`audit_log_write(event="phi_withdrawn", ...)`，让用户重发。

**B（脱敏后继续）**：
```
调用 phi_redact(text=<原文>, min_confidence="medium")
```
把 `redacted` 拿去分析，`mapping` **不发上游**——只在本地告诉用户"占位符对应原文映射我留在这条消息末尾，仅你可见"。
`audit_log_write(event="redaction_applied", phi_summary=<扫描汇总>, input_sample=<原文>)`

答复末尾附一段：
> **审计**：本次分析使用脱敏文本，`[PATIENT_1]`、`[DATE_3]` 等占位符对应你的原文；映射已在你本地屏幕显示，未上传上游。审计记录 ID: `<audit entry ts>`。

**C（本地端点）**：用户必须**再一次**明确说"我确认使用本地/机构端点"。你不代替他确认。确认后：
`audit_log_write(event="phi_on_local_endpoint", provider=<用户告诉你的>, ...)`
然后原文继续。

### Step 5：全程记账

对话结束或用户切换话题时，`audit_log_write(event="session_end", summary="临床数据分析，用户选择 X 路径")`。这样审计日志能还原"哪一天、什么模型、处理过多少条含 PHI 的对话"。

## 特别的坑

- **别猜姓名**。正则会漏中文姓名 + 部分西文姓名；用户提供的段落里凡是"Title-case + Title-case"或"中文姓氏 + 头衔"结构，**默认当姓名处理**，让 phi_scan 补一个 `NAME_TITLECASE` 也算 hit。
- **别忽视间接 identifier**。"63 岁 男性 心内科 住院 3 天"看似无 identifier，但小样本人群下（罕见病 + 特定医院）足以再识别（re-identification）。碰到罕见病 / 罕见组合 + 医院名 → 视同高置信度 PHI。
- **别把审计日志用来存原文**。`audit_log_write.input_sample` 参数会被 SHA-256 后丢弃；`summary` 与 `extra` 会在写入前再次跑 PHI 扫描并打码高置信命中，但这只是防御层，不能当作保存原文的通道。工具仍会截断超长 `extra` 值。

## 与其它 Skill 的关系

- 触发 sensitive-mode 后，`evidence-audit` 仍照走——PHI 处理完了照样要给证据链。
- 触发 sensitive-mode 后，`geo-triage` / `lit-review` 等公开数据 Skill 不冲突——用户可以脱敏后拿公开文献比对。
- 但 sensitive-mode 优先级**最高**：一旦触发，其它 Skill 的输出都要保证不回吐原始 PHI（回吐审计过的脱敏文本）。

## 反例

用户："这是我一个患者，62 岁女性，MRN 1234567，主诉…你看看是不是心梗？"
错误做法：直接开始鉴别诊断。
正确做法：先 phi_scan（会命中 AGE + MRN_LIKE），停下来给用户 A/B/C 选项。

## 边界

- 本 skill 不保证识别所有 PHI（正则局限）。医院用 identifier 差异大，机构应通过 `phi_scan(custom_patterns=...)` 补自己的 MRN / 病案号格式。
- 本 skill 不判断"是否合规"——合规判定是机构 IRB / 隐私官的责任。工具只做技术层面的检测 + 脱敏 + 审计留痕。
