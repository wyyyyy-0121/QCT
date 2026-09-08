# StructuralGuard Standard Benchmark v2

这是 QCT 后续 FormulaGuard 结构压力开发使用的统一同源基准。所有被比较模型必须读取
完全相同的 `public/` 输入；`labels/answer_keys.json` 只供预测完成后的评分器使用。

## 来源与修正

- v2 只从仓库内 `data/structuralguard_standard_v1` 已有的五份工作簿派生。
- 原始交接 ZIP 不需要恢复，也不是模型或生成器输入。
- v1 的 singleton、clean 和 systematic-column 条件保持不变。
- v1 有 3 个 coherent-block 工作簿将错误模板跨列注入，造成 60/100 个
  `expected_formula` 与配对 clean 工作簿同格公式不一致。v2 将这三组注入移回模板原列。
- v1 及其历史结果保持不变，但不得再用其 coherent-block 精确修复率作为晋级证据。

## 固定规模

| condition | 案例 | 错误格 |
|---|---:|---:|
| `singleton` | 5 | 28 |
| `clean` | 5 | 0 |
| `coherent_block` | 5 | 100 |
| `systematic_column` | 5 | 940 |

总计 20 个工作簿、17,272 个公式格和 1,068 个错误格。五个业务场景仍为零售、库存、
项目预算、成绩和 SaaS。

## 证据边界

该数据由已揭盲材料派生，是开发回归与压力诊断基准，不是独立盲测、真实泛化证明或
生产误报率估计。模型不得读取 `labels/`，不得根据答案键决定组边界、候选或拒绝原因。

重新生成和验证：

```bash
python scripts/build_structuralguard_standard_v2.py \
  data/structuralguard_standard_v1 data/structuralguard_standard_v2

python scripts/validate_structuralguard_standard_benchmark.py \
  data/structuralguard_standard_v2
```

正式比较只运行当前 V5 与冻结 V4-R1：

```bash
python scripts/evaluate_structuralguard_standard_benchmark.py \
  data/structuralguard_standard_v2 \
  --methods v5_structural_guard v4_r1 \
  --output results/structuralguard_standard_v2/evaluation.json
```
