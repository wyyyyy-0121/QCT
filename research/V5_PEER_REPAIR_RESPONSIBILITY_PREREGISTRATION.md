# V5 Peer Repair Responsibility 公开开发预注册

日期：2026-09-01  
机制协议：`formulaguard_peer_repair_responsibility_v1`  
批处理协议：`formulaguard_peer_repair_responsibility_run_v1`  
性质：已揭晓公开开发集上的根因责任机制检验，不是独立验证

## 前一阶段失败与新问题

Peer Repair Closure 在公开开发集取得总体 Top-5 `+6.13pp`，但 Enron 只有 `+4pp`，
行动精度只有 41.94%，因此未授权 V5-Core。它证明部分 Peer 异常能被局部修复，却不能
证明这些异常对工作簿输出负责。

标签后诊断发现，冻结 V4 的候选 `candidate_delta` 在同一数据上存在高分切点，但按
`structure_group` 做五折外推后只有 `+4.49pp`、行动精度 47.6%、control 行动率
18.2%，Enron 零增益。该切点不稳定，禁止把约 0.195 或任何事后数值阈值写入新模型。

新问题固定为：Peer 修复是否既改善同一冻结因果锥内的无标签异常能量，又实际改变由该
候选可达的下游可见公式 sink，并且不制造新的求值错误。

## 冻结输入

- 196 个公开工作簿 profile SHA-256：
  `26f7d1d64a65860fb90714a51beb602742d28d1cfefeea8cbadf331b0e1463dc`；
- V4 合并分片 SHA-256：
  `b6ad4b46058e7c5b966bd8faa4b790f52c33a87fa03631fa744fe4a1df28d1f6`；
- Peer 审计合并分片 SHA-256：
  `17fab17b109376e22d339a25d3861aa8c72e5c05a2c410cceab1845938a93890`；
- 候选仍只能是 Peer review Top-1 且必须在 V4 Top-5 之外；没有
  `repair_hypotheses[0]` 时弃权；
- 不读取旧 revealed-trial、SpreadsheetBench 2 或保密 `240+120`。

## 固定责任计算

1. 只在 `WorkbookModel.evaluate(overrides=...)` 和冻结 V4 能量函数中临时覆盖一个公式，
   不修改原模型、不写修复工作簿；
2. 因果锥、公式 descendants 和 sinks 全部从原始工作簿依赖图固定，修复后的引用结构
   不得改变评估范围；
3. 局部范围沿用 V4 的固定三层因果锥、0.70 距离衰减、公式同伴和结构 sink 规则；
4. 精确修复的责任差固定为
   `local_gain - 0.5 * max(local_harm, global_harm)`；
5. 下游改变只在修复前后均可成功求值的原图 descendants 中计算；sink 必须可见、由
   候选在原图中可达，并且修复前后值确实不同；
6. 同时记录最大祖先锥的可见 sink 作为 key-output 诊断，但它不参与本轮行动规则。

不持久化任何修复前后数值本身，只保存能量、计数、布尔变化和错误数量。

## 固定行动规则

`responsibility_pass=true` 当且仅当：

- 精确 Peer 修复责任差严格大于 0；
- 至少一个原图可达、可比较的下游可见公式 sink 在修复后发生变化；
- 修复没有产生任何新的公式求值错误。

三项均为零边界或离散条件；没有学习权重、分位点、候选配额或可调阈值。本轮不要求
Repair Closure 通过，因为上一轮已经证明该条件会系统排除 29 个 `unsupported` 可修复
候选，其中含 11 个公开 gain 且没有 loss/control；新机制检验的是另一种责任证据。

模型动作仍固定为保持 V4 前四位，只在 `responsibility_pass=true` 时把同一个 Peer
Top-1 候选移到第五位，否则完整保留 V4。审查预算固定五格。

## 持久化与标签边界

无标签分片只保存单位 ID、输入哈希、数字名次、能量变化、下游/可见 sink 计数、求值
错误计数和固定规则布尔值。禁止保存格地址、公式、fingerprint、role、支持格、工作簿
文本、工作簿值、事件/结构/队列信息或任何真值标签。所有 196 个分片与完成哈希锁定后，
评分器才可读取既有 220 个公开事件。

## 公开门与停止规则

评分口径与前一轮完全相同：结构组宏平均，10,000 次结构组 bootstrap，种子
`20260901`。进入有界 V5-Core 必须同时满足：

1. 总体 Top-5 相对 V4 至少 `+5pp`；
2. Enron Top-5 相对 V4 至少 `+5pp`；
3. 总体 MRR 不下降；
4. 正残差行动精度至少 75%；
5. V4-hit 损失率不超过 2%，control 唯一工作簿行动率不超过 15%；
6. 总体 Top-5 结构组 bootstrap 95% CI 下界严格大于 0。

任一门失败即停止当前责任规则，不在相同数据上增加 `exact_repair_delta`、sink 数量、
相对变化幅度或 key-output 阈值，也不访问保密 `240+120`。全部公开门通过仍只授权先
提交有界候选和完整预测锁，再一次性进入保密最终验证。

## 声明边界

局部能量、依赖图、反事实修复、输出传播和 sink 分析都有既有工作与本仓库 R2 路线基础，
不能分别声称为新发明。本轮只检验它们是否形成一个可解释、无输出 oracle 的“修复—传播
责任”选择条件；只有锁定后的保密验证通过，才可能成为论文主模型证据。
