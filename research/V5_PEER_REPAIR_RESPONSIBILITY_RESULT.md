# V5 Peer Repair Responsibility 公开开发结果

日期：2026-09-01  
提取源码锁：`8be7502`  
评分源码锁：`f23692c`  
提取收据：`results/peer_repair_responsibility_v1/complete.json`  
评分收据：`results/peer_repair_responsibility_score_v1/receipt.json`

## 完整性

- 196/196 个公开工作簿完成无标签责任提取，24 workers；
- 91 个固定 Peer Top-1 候选中，89 个完成精确修复求值，15 个满足固定责任条件；
- 提取合并分片 SHA-256：
  `3d8e9bd9deffca914f60a6eb8459817cdb521605d2c911d661a3478aba614e7f`；
- 196 个预测分片在标签读取前完成锁定，合并 SHA-256：
  `6d6b19cdb79484322befbd31036957e25a62c3f7dcd7f44417d5a21ea6610de7`；
- 提取阶段 `label_inputs`、`protected_data_inputs`、
  `revealed_label_files_read` 均为空；保密 `240+120` 未访问；
- 评分回执文件 SHA-256：
  `2e26baa2b1b0b48c35f204941333b4b8cadab64e1e09389ccc9daab14469b3d9`。

## 固定规则

仅当精确 Peer 修复在冻结 V4 因果锥中的责任差大于 0、至少改变一个原图可达且可比较的
下游可见公式 sink，并且不产生新求值错误时，才把候选移到 V4 第五位。规则没有学习
权重或数值阈值，不要求上一轮 Repair Closure 通过。

## 主结果

| 指标 | V4-R1 | Responsibility | 差值/风险 | 门槛 | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| 结构组宏 Top-5 | 58.91% | 60.84% | +1.93pp | >= +5pp | **失败** |
| Enron 结构组宏 Top-5 | 52.00% | 52.00% | 0pp | >= +5pp | **失败** |
| 结构组宏 MRR | 0.3961 | 0.3989 | +0.0029 | 不下降 | 通过 |
| 正残差行动精度 | - | 42.86% | 6 gain / 14 error actions | >= 75% | **失败** |
| V4-hit 损失率 | - | 0.91% | 1 / 110 | <= 2% | 通过 |
| control 工作簿行动率 | - | 9.09% | 1 / 11 | <= 15% | 通过 |
| Top-5 bootstrap 95% CI | - | [+0.15pp, +4.31pp] | 下界 > 0 | > 0 | 通过 |

15 个行动工作簿对应 14 个错误事件和 1 个 control 工作簿；错误事件中有 6 gain、7
neutral、1 loss。责任失败组仍包含 22 gain、50 neutral、0 loss 和 3 个 control
工作簿，说明“修复改变 sink”不是 gain 的必要条件，也没有把责任精度提高到目标水平。

队列差异明显：Modified EUSES 得到 +10.83pp，但 Enron、Info1 和 Integer 均为 0，
Historical 只有 +2.11pp。五个结构折中只有 fold 1 超过 +5pp；其余分别为 0、+4pp、
0 和 0。该机制没有跨结构稳定性。

## 判定

七项公开门中总体增益、Enron 增益和行动精度三项失败。因此：

1. 不生成 V5-Core 候选，不访问保密 `240+120`；
2. 不增加 `exact_repair_delta`、sink 数量、key-output 或值变化幅度阈值；
3. 不把 output coupling、sink change 或本结果称为主模型突破；
4. `V4-R1` 继续是唯一正式主排序器；
5. 允许的下一步只是一项跨结构组可学习性审计：使用已经持久化、无标签的闭环、责任、
   V4 和原子特征，判断是否存在能在外折稳定区分 gain/neutral/control 的信息。该审计若
   失败，停止当前 Peer 残差路线，不再手工组合规则。

这条负结果补充了上一轮结论：局部修复真实性和下游输出耦合都不足以单独建立无 oracle
根因责任。它们可以作为论文消融，但不是正式模型。
