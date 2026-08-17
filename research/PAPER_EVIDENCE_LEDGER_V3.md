# FormulaGuard v3 论文证据台账

这份台账约束论文中的每个主要结论。没有对应原始文件、评价指标和适用
范围的句子，不进入摘要和结论。

| 编号 | 可写入论文的结论 | 直接证据 | 当前状态 | 不得扩大的边界 |
|---|---|---|---|---|
| E1 | 在可控传播基准上，frozen-v3能够定位六类人工注入的静默源错误 | `results/v3_full/summary.csv`、`by_error.csv`、`by_depth.csv` | 已完成 | 不能据此声称能处理任意真实表格 |
| E2 | v3在该合成基准上优于v2，且配对bootstrap区间不跨0 | `results/v3_full/paired_comparison.json` | 已完成 | 差值只适用于此基准与冻结配置 |
| E3 | 合成候选覆盖率高，但生成器与修复器存在设计耦合 | `results/v3_full/benchmark_independence.audit.json` | 已完成，高风险 | 必须与E1同时披露，不能只报100%覆盖率 |
| E4 | 原frozen-v3在10个Enron开发事件上没有超过v2 | `results/enron_pilot/external_analysis.json` | 已完成，负面结果 | 10例小于15例阈值，不作确认性推断 |
| E5 | v3-real B不改变不同v2分数组，只把反事实证据作为并列裁决和证据标签 | `formulaguard/localize.py`、单元测试、`results/enron_pilot_real_b/` | 开发集验证完成 | 不能称为真实数据上精度提升 |
| E6 | Enron标签按36个错误事件而非630个单元格统计，30个公式事件可评 | `data/external/enron/manifest.audit.json`、`inventory.audit.json` | 已完成 | 不能把多单元格范围拆成独立样本扩大样本量 |
| E7 | 外部测试集在规则冻结前保持未运行，开发/测试清单不相交 | `data/external/enron/split_lock.json` | 已锁定 | 测试集运行后不得再改规则或阈值 |
| E8 | v3-real在20个未见Enron事件上的定位效果 | `results/enron_test_v3_real/` | 待运行 `run_enron_test.cmd` | 未完成前不得写结果性结论 |
| E9 | v3在100至5000公式规模下的时间成本 | `results/v3_full/performance_v3.csv` | 待大型实验 | 旧v2性能文件不能代替v3 |
| E10 | 公式计算与LibreOffice一致性 | `results/v3_full/libreoffice_validation.csv` | 已完成 | 这验证计算一致性，不验证错误标签正确性 |

## 论文中心贡献的限定表达

建议表述：

> 本研究提出一种“候选修复支持的下游反事实诊断责任排序”：在不使用正确
> 输出真值的前提下，把公式模式、依赖结构和候选替换后的下游变化组合为
> 可审计证据，并在证据不足时明确降级或保留基础排序。

不使用下列表述：

- “解决了Excel公式错误检测问题”；
- “在真实表格上达到100%准确率”；
- “证明某单元格是错误的因果根源”；
- “自动修复所有静默公式错误”。

## 最终结论门槛

只有20个未见外部测试事件完成后，才允许填写E8。若v3-real未超过强基线，
论文仍保留方法贡献，但结论改为“反事实证据分级提高了解释可审计性，真实
定位精度未显示稳定提升”。负面结果和失败案例不得删除。
