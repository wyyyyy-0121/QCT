# V5 Peer Repair 特征可学习性审计预注册

日期：2026-09-01  
协议：`formulaguard_peer_repair_learnability_audit_v1`  
性质：已揭晓公开开发集上的嵌套结构折审计，不是独立验证，也不是正式 V5-Core

## 研究问题与止损边界

Peer Repair Closure 和 Peer Repair Responsibility 分别证明了部分候选可被局部修复、
部分修复会传播到可见输出，但两条固定规则都没有通过公开门。最后允许的问题只有一个：
这些已经锁定的无标签证据中，是否存在能跨结构组稳定区分有益动作、无效动作和有害动作的
低复杂度线性信号。

本审计不得重新提取工作簿、增加候选、搜索特征子集、搜索正则强度、改变损失权重或按结果
增加阈值。五个预先指定的特征视图全部失败时，当前 Peer 残差路线终止；不得继续在同一
公开数据上手工组合 Closure、Responsibility、`candidate_delta` 或 sink 阈值。

## 冻结公开输入

- 196 个 observation profiles：
  `26f7d1d64a65860fb90714a51beb602742d28d1cfefeea8cbadf331b0e1463dc`；
- 220 个公开事件表：
  `c68e2436957a83f6e8e80e6de6c5a3d45ca35b71e162ebc928275352ba90dd34`；
- V4 合并分片：
  `b6ad4b46058e7c5b966bd8faa4b790f52c33a87fa03631fa744fe4a1df28d1f6`；
- Peer 原子审计合并分片：
  `17fab17b109376e22d339a25d3861aa8c72e5c05a2c410cceab1845938a93890`；
- Closure 合并分片：
  `74dea9153e9e6422f66ba4f7d99534d8a01d343dc7cb33752060aa050dea0f3d`；
- Responsibility 合并分片：
  `3d8e9bd9deffca914f60a6eb8459817cdb521605d2c911d661a3478aba614e7f`。

只允许上述公开输入。禁止读取旧 revealed trial、SpreadsheetBench 2 和保密
`/home/ayaka/code/FormulaGuard_240_120/`。

## 固定候选与动作

每个工作簿只有一个可能动作：Peer review Top-1 必须位于 V4 Top-5 之外，并且必须有
锁定的第一修复假设。否则始终弃权。动作保持 V4 前四位不变，只把该候选移到第五位；
审查预算固定为五格。五个特征视图共享完全相同的候选、折和动作，因此差异只来自特征。

## 五个固定特征视图

所有特征来自标签读取前锁定的分片。不得使用 unit ID、工作簿哈希、文件名、格地址、公式
文本、结构组、cohort 或事件字段作为模型特征。连续量在每个训练折内用中位数填补、均值
标准化并增加 missing indicator；布尔量保持 0/1。常数列保留但不产生有效系数。

1. `v4`：候选与第五位的 V4 名次、V4 证据数值、V4 诊断状态 one-hot，以及对应差值；
2. `atomic`：Peer/Combined/Role/Impact 的名次、分数和 margin，原子 Peer 证据、工作簿
   规模比率、原子状态 one-hot，以及候选相对第五位的原子差值；
3. `closure`：候选修复前后 evidence tier、Peer 名次、缺陷/分歧/支持/margin/competition/
   role-outlier 数值及差值，全局缺陷和状态计数及差值，修复可用/执行、状态 one-hot、
   anomaly/actionable/review/一致性、无新增异常、可逆和 closure-pass 布尔量；
4. `responsibility`：局部/全局能量、gain/harm/side-effect/exact delta，scope、descendant、
   sink、求值错误和修复错误计数，以及 repair 可用、正 delta、sink change、key-output、
   no-new-error 和 responsibility-pass 布尔量；
5. `combined`：上述四组的并集，不增加交互项。

实现必须把每个视图的精确字段顺序写入结果。禁止特征筛选或按外折表现删除字段。

## 固定学习目标

每个训练事件对固定候选产生一个残差效用：

- V4 未命中而动作后 Top-5 命中：`+1`；
- V4 已命中而动作后丢失：`-4`；
- clean control 上采取动作：`-2`；
- 其余：`0`。

同一 `structure_group` 的全部训练事件权重之和固定为 1。每个视图只拟合一个带截距的
closed-form NumPy ridge，`lambda=1.0`；不搜索超参数，不引入 sklearn。

## 嵌套结构五折与校准

`structure_group` 继续使用冻结 SHA-256 映射到 `0..4`。对每个
`outer_fold=i`：

- 外测折：`i`；
- 校准折：`(i+1) % 5`；
- 训练折：其余三个折。

训练完成后只在校准折枚举模型实际分数形成的阈值。有限阈值必须同时满足：至少恢复 3 个
公开错误事件、正残差行动精度至少 75%、V4-hit loss rate 不超过 2%、control 唯一
工作簿行动率不超过 15%。合格阈值按结构组宏 Top-5 增益、恢复数、较少行动工作簿、
较高阈值依次选择。没有合格阈值时该外折固定全弃权，禁止借用其他折阈值。

## 外折汇总门

每个视图只汇总五个从未参与其训练或校准的外折预测。使用结构组宏平均，并以种子
`20260901` 对结构组做 10,000 次 bootstrap。一个视图必须同时满足：

1. 总体 Top-5 相对 V4 至少 `+5pp`；
2. Enron Top-5 相对 V4 至少 `+5pp`；
3. 总体 MRR 不下降；
4. 正残差行动精度至少 75%；
5. V4-hit loss rate 不超过 2%；
6. control 唯一工作簿行动率不超过 15%；
7. 总体 Top-5 结构组 bootstrap 95% CI 下界严格大于 0。

同时报告五个外折各自指标、有限校准阈值数量和五个视图全部结果。五视图是预先指定的
开发比较，不把单个 bootstrap 区间解释为多重比较校正后的显著性证据。

## 决策与后续授权

- 五个视图全部失败：记录负结果，停止 Peer 残差路线，不访问保密 `240+120`；
- 至少一个视图通过：只授权另写候选冻结协议。通过视图按总体 Top-5 增益、Enron 增益、
  MRR 增益、行动精度、较少特征数和固定顺序
  `v4, atomic, closure, responsibility, combined` 选择；
- 公开通过不等于论文突破。必须先提交源码、配置、完整公开外折预测与哈希，再生成唯一
  锁定候选，最后一次性进入保密 `240+120`；
- 保密验证未通过时，`V4-R1` 仍是唯一正式主排序器。

## 声明边界

本审计只能回答“锁定特征是否包含跨结构可学习信号”。Ridge、嵌套分组交叉验证、局部
修复、依赖图、sink 和反事实能量都不能作为新的学术发明单独主张。只有机制、公开外折和
保密独立验证共同成立后，才允许评估其是否可写为论文主模型。
