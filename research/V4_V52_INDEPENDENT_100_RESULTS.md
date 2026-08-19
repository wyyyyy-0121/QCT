# V4/V5.2 扩展独立验证结果（100 例合并集）

## 证据完整性

- 公开 100 例工作簿先由冻结 V4 与冻结 V5.2-B 生成预测并写入
  `results/v4_v52_independent_100_locked/prediction_lock.json`；
- 锁定元数据记录 `events=100`、`label_inputs=[]`、`worker_processes=24`，且
  V5.2 的核心排序在 100/100 工作簿中与 V4 相同；
- Batch-2 私密压缩包的 SHA-256 为
  `3c2d82eb6bcbd593df06a4bc2293b8a2f5a7553ac6294fb17343acdd1e70687b`，
  与预测前公开承诺相同；
- 解压的 `v4_v52_labels.csv` 与 `v4_v52_exceptions.csv` 分别匹配预承诺的
  SHA-256 `6cd81...4ab91a` 和 `2d28...a5514`；
- 标签和例外表各有 100 个唯一 ID，ID 集合精确匹配，六类错误覆盖为
  17/17/17/17/16/16。

## 必须保持的 Cohort 边界

`independent_001` 至 `independent_015` 已在早期 Cohort-1 中揭盲，不能重新称作
新增盲测。`independent_016` 至 `independent_100` 的 85 例才是 Cohort-2 的新增
独立验证。下表因此分别报告 15、85 和合并 100 例；论文的主要扩展结论必须使用
Cohort-2，而不是用合并均值掩盖差异。

| 指标 | Cohort-1（15，既有） | Cohort-2（85，新增独立） | 合并（100，次要汇总） |
|---|---:|---:|---:|
| V4 Top-1 | 53.33% | 17.65% | 23.00% |
| V4 Top-3 | 86.67% | 32.94% | 41.00% |
| V4 Top-5 | 86.67% | 56.47% | 61.00% |
| V4 MRR | 0.6726 | 0.3311 | 0.3823 |
| V4 EXAM | 0.0758 | 0.0851 | 0.0837 |
| 精确修复率 | 73.33% | 50.59% | 54.00% |

Cohort-2 的事件 bootstrap 95% 区间为：Top-1 `[9.41%, 25.88%]`，Top-3
`[23.53%, 42.35%]`，Top-5 `[45.88%, 67.06%]`，MRR `[0.2608, 0.4039]`，
EXAM `[0.0647, 0.1083]`。这些区间说明新集上的下降不能被表述为小样本偶然波动。

## 分类型失败信号

| Cohort-2 错误类型 | 样本数 | V4 Top-5 | V4 MRR | 精确修复 |
|---|---:|---:|---:|---:|
| reference_offset | 14 | 92.86% | 0.3893 | 0.00% |
| copy_offset | 14 | 85.71% | 0.4548 | 100.00% |
| operator | 15 | 93.33% | 0.6400 | 100.00% |
| absolute_relative_reference | 14 | 64.29% | 0.3710 | 100.00% |
| function_replacement | 14 | 0.00% | 0.0439 | 0.00% |
| range_boundary | 14 | 0.00% | 0.0653 | 0.00% |

`function_replacement` 与 `range_boundary` 的 28 个 Cohort-2 事件均未进入 V4
Top-5。这是跨类型泛化不足的明确失败机制，不是可以忽略的总体噪声。

## V5.2-B 的边界

V5.2-B 不改变 V4 的 Top-5。Cohort-2 中，救援位激活 12 次、正确 7 次，精确率
58.33%，新增 Review@6 命中 7 次；正确例外暴露为 5/85（5.88%）。因此它通过了
预登记的“安全辅助审查位”门槛，但不能声称提升 V4 的 Top-5、MRR 或主定位能力。

## 结论与后续约束

这份结果证明 V4/V5.2 的锁定、标签隔离和审计流程有效，但不支持“V4 在六类静默
公式错误上稳定高精度泛化”的主张。不得使用这 100 个已揭盲标签调整 V4、V5.2 或
启动一个据此调参的 V6。若研究继续，需要先把这两个明确失败类型转化为可证伪的
机制假设，在新的开发集上验证，再由第三方提供新的独立集。

原始可复核产物：

- `results/v4_v52_independent_100_locked/prediction_lock.json`；
- `results/v4_v52_independent_100_scored/independent_summary.json`；
- `results/v4_v52_independent_100_scored/independent_scored_events.csv`；
- `results/v4_v52_independent_100_scored/independent_audit.json`。
