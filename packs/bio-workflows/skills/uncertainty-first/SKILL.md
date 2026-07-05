---
name: uncertainty-first
description: 所有科研工作流的收尾强制标准——每次给出研究性结论前，必须暴露不确定性五段面板：Known knowns / Known unknowns / Conflicts / Missing data / Next experiment。触发：任何文献综述、靶点发现、老药新用、临床试验分析、组学分析、机制假设、证据审计的结论阶段；也用于"帮我找盲区"、"这个结论还缺什么"、"有哪些没搞清楚的"、"下一步该做什么实验"、"这个方向的未知数"。这是一个横切标准，其它 workflow skill 收尾时都要引用它。
---

# 不确定性优先（uncertainty-first）

研究者最需要 AI 帮的，不是"告诉我已知的"，而是**帮我看见我没看见的盲区**。所以本项目的所有科研工作流，结论阶段一律强制输出五段"不确定性面板"。**没有这五段的研究性回答，视为未完成。**

## 五段契约（一段都不能省）

1. **Known knowns（已知已确证）**——有可核对证据支持的结论。每条必须带：证据等级 + 适用边界（物种 / 人群 / 疾病阶段 / 样本量）。不是"我们知道 X"，而是"在【人类 / II 期 / n=245 / 转移性】范围内，X 成立"。
2. **Known unknowns（已知的未知）**——你**知道自己不知道**的问题。检索到了但证据不足、或问题本身尚无定论的点。这一段空着，通常说明检索还不够深。
3. **Conflicts（证据冲突 / 反证）**——相互矛盾的证据、方向相反的研究、断言与实际的错配（如"结论谈人类，证据是动物"）。**主动找反例**，不是等用户质疑。
4. **Missing data（缺失数据 / 盲区）**——**你不知道自己不知道**的邻域：没人做过的对照、缺失的人群分层、没报告的样本量、没有前瞻验证的回顾性发现。这一段是这个 skill 最大的价值。
5. **Next experiment（下一步实验建议）**——把上面三段（未知/冲突/缺失）转成 1–3 个**具体、可执行**的下一步：什么设计、什么人群、什么终点、验证哪条 claim。不是"需要更多研究"这种废话。

## 怎么生成（别纯手写）

如果启用了 bio-audit，**不要凭感觉写五段**——用工具把可派生的部分自动挖出来：

1. 先把结论拆成 claim，走 `evidence_graph`（每条 claim 绑证据 + 物种 + 样本量 + 阶段 + 冲突 + 反证 + 适用边界）。
2. 把 `evidence_graph` 的 `claims` 直接喂给 `uncertainty_ledger`，它会：
   - supported claim → Known knowns（带边界）
   - unsupported claim → Known unknowns
   - graph 里的 conflict / counter-evidence → Conflicts
   - 窄边界（仅临床前 / 无样本量 / 无分期）→ Missing data
   - 自动给出 Next experiment 候选
3. 你再补充工具挖不到的领域先验（比如"这个方向十年前的大试验失败过"），用 `extra` 参数并进去。

`uncertainty_ledger` 直接返回渲染好的 Markdown，原样贴进答复末尾。

## 反例（不要这样）

> 结论：EGFR 在 GBM 中仍有靶点价值，建议进一步研究。

问题：全是 Known knowns 的口吻，没有边界（哪种干预？成人还是儿童？），没暴露"EGFR-TKI 在 GBM 反复失败"这个 Conflict，没说缺什么数据，"进一步研究"不是可执行的 Next experiment。

正确收尾至少是：

> **Known knowns**：EGFR 在 ~57% GBM 中扩增/突变（EGFRvIII），关联证据等级=功能基因组学+人类样本 [PMID..]；适用边界：成人原发 GBM。
> **Known unknowns**：EGFRvIII 特异性疗法能否穿过血脑屏障并维持疗效，尚无定论。
> **Conflicts**：多项 EGFR-TKI III 期（如 depatux-m）在 GBM 未达 OS 终点 [NCT..]，与"靶点有价值"存在张力——价值可能不在 TKI 而在 ADC / 疫苗 / CAR-T。
> **Missing data**：缺 EGFRvIII CAR-T 在初诊（而非复发）人群的前瞻数据；多数失败试验未按 EGFR 状态分层。
> **Next experiment**：EGFRvIII+ 初诊 GBM 中，CAR-T 联合检查点抑制 vs 标准放化疗的随机 II 期，主终点 PFS，按 MGMT 甲基化分层。

## 边界

- 五段里**允许某段为空**，但要显式写"（无）"并说明为何——空的 Conflicts 可能意味着检索有偏，空的 Missing data 几乎总是检索不够。
- 这个标准**叠加**在具体 workflow skill 之上，不替代它们的检索/审计流程；它是所有流程的统一收尾。
