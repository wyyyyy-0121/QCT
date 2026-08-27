# FormulaGuard 版本沿革与命名迁移规则

状态：2026-08-27起生效。本文定义论文、演示和新公共接口使用的正式版本名。
旧源码、冻结配置、Git标签、结果目录和预测锁中的历史标识不得改写。

## 1. 为什么重新编号

旧称V5、V5.2和V6的三个方法都直接调用冻结V4，未替换V4主排序架构：

- 旧V5只把“公式模式精英＋V4强反事实证据”候选移动到V4排序前部；
- 旧V5.2完全不改变V4排序，只增加一个可空的第六人工复核位；
- 旧V6先计算完整V4排名，再根据FFC/BSS语义证据最多把一个单元格插入第3或第5名。

因此它们是V4上的机制研究，不应在论文中被包装成三代彼此独立的核心模型。
真正的V5版本号保留给不调用`v4_scores`作为最终排序底座的核心重构。

## 2. 正式映射

| 论文与新接口正式名称 | 历史代码/结果名称 | 方法身份 | 结论 |
|---|---|---|---|
| FormulaGuard V4.1-PCG | legacy V5 / `v5-pcg-r1` | 模式—反事实直接重排 | Enron安全回归下降，否决 |
| FormulaGuard V4.2-Review-B | legacy V5.2-B / `v5.2-b` | 不干扰V4 Top-5的第六复核位 | 冻结辅助模块 |
| FormulaGuard V4.3-Semantic | legacy V6 / `v6-semantic-r1` | FFC/BSS语义候选与单格受限重排 | 机制有效，未通过主模型冻结门槛 |
| FormulaGuard V5-Core | `formulaguard_v5_core_*` | 候选中心、多证据责任的核心重构 | 开发中，尚未冻结 |

V4.3的A/B/C只是同一机制实验的预登记变体，不再写成三个模型版本。

## 3. 新公共接口

```python
from formulaguard import v4_1_scores, v4_2_review, v4_3_scores

v41 = v4_1_scores(model)
v42 = v4_2_review(model, variant="b")
v43 = v4_3_scores(model, variant="b")
```

新接口在输出证据中使用`model_version=v4.x-...`，并保留
`legacy_model_version`。排名、候选、救援决定和数值不发生变化。

旧接口继续可用，以便复现已经提交的命令与结果：

```text
formulaguard_v5       -> V4.1-PCG的历史别名
v5.2-b                -> V4.2-Review-B的历史别名
formulaguard_v6_b     -> V4.3-Semantic-B的历史别名
```

## 4. 不允许批量改写的对象

以下对象属于审计证据，不做查找替换：

- `formulaguard/v5.py`、`formulaguard/v52.py`、`formulaguard/v6.py`；
- `research/frozen_config_v52.json`及其记录的源码SHA-256；
- `research/V6_VALIDATION_PRECOMMIT.json`记录的方法和源码SHA-256；
- `freeze-v4-r1`、`v5.2-lock`等既有Git标签；
- `results/v5*`、`results/v6*`既有目录与原始CSV/JSON；
- 旧方法规格、开发日志、预测锁和揭盲评分中的原始版本字段。

改写这些文件会让历史命令、锁文件或哈希不再对应原实验，属于破坏复现性，
不是正常的版本重命名。

## 5. 论文写法

第一次出现时使用：

> V4.3-Semantic（实验代码历史标识为V6）

后文只写V4.3。附录给出本表以及旧目录映射。不得把旧V5/V5.2/V6描述为三次
完整核心换代；应把它们作为V4主模型之后的直接重排、非干扰复核和语义重排
三项机制实验。

## 6. 真正V5的最低定义

新V5必须同时满足：

1. 不调用`v4_scores`取得最终基础排序；
2. 在公式排名前生成并评估候选修复；
3. 统一建模结构、图传播、反事实特异性和合法例外；
4. 不依靠固定“插入第3/第5名”覆盖V4结果；
5. 使用全新开发和锁定验证数据，旧85例与V4.3内部360例只作回顾性诊断。

当前`formulaguard/v5_core.py`已经满足以上架构边界，但只有通过全新锁定验证并
完成冻结，论文才将它作为正式主模型；开发失败时仍保留V4为主模型。
