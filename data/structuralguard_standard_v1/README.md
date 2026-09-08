# StructuralGuard Standard Benchmark v1

这是后续 FormulaGuard、StructuralGuard 及其变体共同使用的**同源压力基准**。
它只由 `StructuralGuard_handoff_20260903_complete.zip` 中的五份工作簿派生，不能
当作独立真实数据、泛化证明或论文最终测试集。

## 固定来源

- source archive SHA-256: `49ced27ddafe0d68b2f6c573bb61706b09d0b4a97eb2e9f08aaaa070c1a2a4a1`
- source workbooks: 5
- formula templates: 4,318
- generated cases: 20 (five per condition)
- injected errors: 1,068 (28 + 0 + 100 + 940)

`public/manifest.csv` 和 `public/workbooks/` 是模型输入；`labels/answer_keys.json`
是揭盲评分标签。标签不得用于模型调参后再声称盲测。

## 四个固定条件

| condition | 内容 | 主要检验 |
|---|---|---|
| `singleton` | ZIP 原始五本，保留 28 个单点注错 | 局部异常定位与候选修复 |
| `clean` | 修复全部 28 个原始注错 | 正常表误报安全性 |
| `coherent_block` | 每本从 clean 出发，在一个公式列连续 20 格施加同一错误模式 | 局部多数被一致污染时的盲区 |
| `systematic_column` | 每本从 clean 出发，在一个公式列所有公式格施加同一错误模式 | 全局一致系统错误的盲区 |

块错误和整列错误不是新的业务真值；它们是由已公开的错误模板平移得到的反事实
压力样本。每个标签都记录 `category`、`injected_formula`、`expected_formula`、
`source_template_cell` 和 `mutation_condition`。

## 统一指标

对有标签条件报告完整排名的 AP、Recall@1/5/10/20 和候选修复精确匹配率；对
`clean` 只报告固定预算 Top-K 误报或模型原生 review 集行动率。原生 `review`、
`repair_candidate` 与完整排名必须分开，不得用一个模型的 review 结果和另一个模型
的 Top-K 结果直接比较。

生成和校验：

```bash
python scripts/build_structuralguard_standard_benchmark.py \
  StructuralGuard_handoff_20260903_complete.zip data/structuralguard_standard_v1

python scripts/evaluate_structuralguard_standard_benchmark.py \
  data/structuralguard_standard_v1 \
  --structuralguard-code /path/to/StructuralGuard/01_code
```

评估器遇到公式语法或接口不支持时记录 `error`，不把未完成的子集分数汇总成完整
结果。模型代码、参数和数据版本必须随结果回执记录；本目录的 `SHA256SUMS.txt`
绑定当前数据内容。

## 解释边界

StructuralGuard 的设计目标是结构离群检测、人工复核压缩和邻居平移候选；FormulaGuard
V4 的目标是无输出真值的静默源错误根因定位、因果传播责任和受约束修复。两者在
`singleton` 上可比较定位排序，但整列一致错误的失败不等于任何一个模型能证明业务
语义正确。正式晋级仍需未参与开发的真实工作簿和外部基线。
