# StructuralGuard Standard Benchmark v1

状态：2026-09-03，已生成、复算并完成 StructuralGuard 评估。该基准是由同一
StructuralGuard 交接 ZIP 派生的反事实压力套件，不是独立真实数据集，也不授权
任何新版本冻结或晋级。

## 任务边界

FormulaGuard V4-R1 的预期效果是：在不知道输出真值的条件下，定位最可能的**静默
源公式错误**，区分根因与下游传播，并在受约束时提供可审计候选修复。它的评价重点
是源定位、传播责任和修复候选，而不是把所有结构离群都当作错误。

StructuralGuard 的交接目标是：不使用神经网络，以公式层次结构、局部/区域一致性、
依赖拓扑和常量特征发现异常，压缩人工复核范围，并从邻居公式生成候选修复。它对
“单点偏离稳定复制模板”的问题更直接，但没有业务语义或全局一致性真值证明。

因此，两者在单点注错定位上可以比较；在成片或系统性错误上必须报告压力条件，不能
用一个 AP 数字宣称互相替代。

## 数据冻结

- 来源：`StructuralGuard_handoff_20260903_complete.zip`
- 来源 SHA-256：`49ced27ddafe0d68b2f6c573bb61706b09d0b4a97eb2e9f08aaaa070c1a2a4a1`
- 五本工作簿，4,318 个公式模板，20 个派生案例
- 四条件：`singleton` 5、`clean` 5、`coherent_block` 5、`systematic_column` 5
- 注入计数：28、0、100、940；总计 1,068
- 数据目录：`data/structuralguard_standard_v1/`
- 交付压缩包：`outputs/StructuralGuard_standard_benchmark_v1.zip`

模型只读 `public/manifest.csv` 和 `public/workbooks/`；揭盲评分使用
`labels/answer_keys.json`。生成器、统一评分器和哈希清单分别为：

- `scripts/build_structuralguard_standard_benchmark.py`
- `scripts/evaluate_structuralguard_standard_benchmark.py`
- `data/structuralguard_standard_v1/SHA256SUMS.txt`

## 已完成的漏洞压力证据

StructuralGuard 在这四个条件上的完整结果写入
`results/structuralguard_standard_v1/structuralguard_evaluation.json`：

| 条件 | 错误数 | Macro AP | Top-5 召回 | 原生 review | 精确修复 |
|---|---:|---:|---:|---:|---:|
| singleton | 28 | 1.0000 | 25/28 (89.29%) | 28/32 (87.50% precision) | 28/28 |
| clean | 0 | 不适用 | 不适用 | 0/5 本有行动 | 不适用 |
| coherent_block | 100 | 1.0000 | 25/100 (25.00%) | 100/108 (92.59% precision) | 2/100 |
| systematic_column | 940 | 0.2169 | 6/940 (0.64%) | 0/5 本有行动 | 0/940 |

这构成了一个可重复的存在性反例：模型能识别局部边界，但当同一错误模式成为局部
或整列多数时，结构一致性本身会掩盖错误。它不能证明模型在所有真实表格都失败，
但足以否定“结构高分等于业务正确”或“单点满分可外推到系统错误”的说法。

## V5 Structural Guard 候选结果

`formulaguard/v5_structural_guard.py` 的候选版本为
`v5-formulaguard-silent-source-r1`。它只接收工作簿公式、依赖图和表头文本，独立生成
完整排名；不调用 `v4_scores`、不读取 `labels/answer_keys.json`，候选公式只作解释，
不会自动修改源工作簿。

最终回执：`results/structuralguard_standard_v1/v5_structural_guard_evaluation_final.json`。

| 条件 | 案例 | 错误数 | Macro AP | Top-5 召回 | 精确修复 |
|---|---:|---:|---:|---:|---:|
| singleton | 5 | 28 | 1.0000 | 25/28 (89.29%) | 28/28 |
| clean | 5 | 0 | 不适用 | 固定 Top-20：0/100 误报 | 不适用 |
| coherent_block | 5 | 100 | 0.6210 | 17/100 (17.00%) | 17/100 |
| systematic_column | 5 | 940 | 1.0000 | 25/940 (2.66%) | 180/940 |

在完全相同的五本 `singleton` 案例上，冻结 `V4-R1` 的独立回执为
`results/structuralguard_standard_v1/v4_r1_singleton_final.json`：Macro AP
`0.667224`、Top-5 `16/28 (57.14%)`、精确修复 `21/28`。因此候选在该同源套件上
超过 V4：AP 提升 `0.332776`，Top-5 多命中 9 个错误，精确修复多 7 个。

这只是同一交接 ZIP 派生的机制压力套件上的候选证据，不是独立真实数据，也不证明
真实泛化或正式 `V5-R1` 晋级。coherent/systematic 条件仍显示候选的覆盖和修复能力
不等价：整列错误可以被完整排序但无法保证每格候选修复正确，需在外部工作簿上继续
做盲测和安全门审计。

## 统一使用规则

1. 后续模型不得读取 QCT 旧数据或把历史数据混入本基准；所有方法共享本目录的五本
   来源和四个固定条件。
2. `singleton` 报告 AP、Recall@K 和修复精确率；`clean` 报告固定预算误报或原生
   review 行动率；两种指标不得混算。
3. `coherent_block` 和 `systematic_column` 是压力测试，不是新的业务标签；必须
   报告错误覆盖比例、Top-K 召回和是否产生整列盲区。
4. 模型不支持某种公式时记录 `unsupported/error`，不得把剩余可运行子集汇总成完整
   结果。
5. 该同源套件只能证明可复算的机制边界。要宣称真实泛化或新版本超越 V4，仍需
   未参与开发的真实工作簿、外部基线和预先冻结的安全门。
