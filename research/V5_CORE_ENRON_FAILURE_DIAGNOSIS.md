# V5-Core Enron 失败机制诊断

> 结论先行：Enron 安全门槛确实失败，当前 V5-Core 不能取代 V4。本报告是揭晓标签后的回顾性诊断，只解释失败，不参与模型训练、调参或选择。

## 1. 总体结果

| 方法 | Top-5 | MRR | EXAM |
|---|---:|---:|---:|
| V4 | 50.0% | 0.3825 | 0.2419 |
| V5-Core Rule | 46.7% | 0.2946 | 0.2572 |
| V5-Core Learned | 40.0% | 0.2665 | 0.1743 |

规则头相对 V4 的 MRR 差为 **-0.0880**；学习头差为 **-0.1160**。两者都超过预登记允许的 -0.01 退化。

## 2. 解析覆盖与主排序泛化

- 30 个事件中，真实源包含不支持语法的事件为 **0** 个；真实源仍受支持的事件为 **30** 个。
- 7 个工作簿共出现 826 个不支持公式；兼容适配器只把这些公式放到完整排名尾部，没有改动冻结的 V5-Core 核心。
- 在真实源受支持的 30 个事件上，V4/Rule/Learned 的 MRR 分别为 **0.3825 / 0.2946 / 0.2665**。

因此，退化不能只归因于 Excel 语法覆盖；即便真实源公式可解析，候选中心证据在真实表格上的排序泛化仍然不足。

## 3. 事件级升降

- 规则头：10 胜 / 5 平 / 15 负。
- 学习头：14 胜 / 3 平 / 13 负。

最大退化事件如下（MRR 差为 V5-Core − V4）：

| 头 | 事件 | V4名次 | V5名次 | MRR差 | 源公式不支持 |
|---|---|---:|---:|---:|---:|
| Rule | enron_event_28 | 1 | 8 | -0.8750 | 否 |
| Rule | enron_event_03 | 1 | 5 | -0.8000 | 否 |
| Rule | enron_event_06 | 1 | 5 | -0.8000 | 否 |
| Rule | enron_event_19 | 1 | 5 | -0.8000 | 否 |
| Rule | enron_event_07 | 2 | 21 | -0.4524 | 否 |
| Learned | enron_event_28 | 1 | 115 | -0.9913 | 否 |
| Learned | enron_event_22 | 1 | 36 | -0.9722 | 否 |
| Learned | enron_event_19 | 1 | 14 | -0.9286 | 否 |
| Learned | enron_event_05 | 1 | 10 | -0.9000 | 否 |
| Learned | enron_event_03 | 1 | 4 | -0.7500 | 否 |

## 4. 研究决策

1. 不修改 V5-Core 权重、阈值或候选规则来迎合 Enron；Enron 已经是回顾性安全集。
2. 当前开发审计保持失败，V5-Core 暂不允许取代 V4，也不生成成功冻结标签。
3. 仍运行预先设计的 480 例锁定内部验证，但其定位为**独立诊断证据**，不是用来覆盖或‘救回’已经失败的 Enron 门槛。
4. 若锁定验证明显优于 V4，则论文应同时报告‘合成泛化强、真实语料安全性不足’；若锁定验证也退化，则 V5-Core 作为有完整机制与负结果的核心重构保留。

## 5. 可复算文件

- `results/v5_core_development/enron_failure/event_diagnostics.csv`
- `results/v5_core_development/enron_failure/cohort_metrics.csv`
- `results/v5_core_development/enron_failure/driver_summary.json`
