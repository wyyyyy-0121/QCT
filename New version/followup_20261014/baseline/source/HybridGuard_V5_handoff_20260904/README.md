# HybridGuard 大面积公式错误实验

本项目在同一份约 7.5 万非空单元格的合成 Excel 上比较：

1. 用户提供的 StructuralGuard 1.0.0；
2. 用户提供的 FormulaGuard V5 structural-semantic guard；
3. 分层 HybridGuard：StructuralGuard 局部扫描 + 跨平行工作表连续组共识 + FormulaGuard 代表点安全验证。

## 研究边界

- 测试工作簿是合成数据，只验证机制，不证明真实工作簿泛化。
- HybridGuard 的跨表组检测要求至少三份结构可比的平行工作表。
- FormulaGuard 源码来自 `wyyyyy-0121/QCT` 的 `codex/linux-migration` 分支，按 MIT 许可证使用；许可证保存在 `vendor/FORMULAGUARD_LICENSE.txt`。
- StructuralGuard 来自用户提供的交接包。
- 答案键为独立 JSON，运行三个模型时均不作为模型输入，只在运行结束后评分。

## 原分工

1. StructuralGuard：快速扫描全工作簿，提供局部结构异常和边界证据。
2. FormulaGuard V5：重点处理正常表中的稀疏、偶发公式错误，提供排名和候选公式。
3. 跨表多数共识：定位连续块、整列等内部一致但跨表不一致的大面积错误。
4. HybridGuard：对异常组抽取代表点验证，验证通过后将候选修复传播到整组。

## 运行

Python 侧依赖可用 `pip install -e .` 安装。工作簿生成脚本使用 Codex 内置的 `@oai/artifact-tool` 2.8.52；若在普通 Node 环境中没有该私有运行库，请直接使用随交付提供的已生成测试工作簿，而不是重新生成。

```powershell
$python = "C:\Users\czk\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$node = "C:\Users\czk\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"

& $node scripts\build_large_error_workbook.mjs output\multi_suite
$env:PYTHONPATH = "$PWD\src"
& $python -m hybridguard.runner_hierarchical output\multi_suite\sparse_seed101.xlsx output\multi_suite\sparse_seed101_truth.json --output-dir output\results
```

也可以使用一键脚本（默认使用 PATH 中的 `python` 和 `node`）：

```powershell
.\run_all.ps1
```

如需额外重跑全工作簿V5基线，可使用 `.\run_all.ps1 -RunFullFormulaGuard -CandidateLimit 24`。

六工作簿、多随机种子实验使用：

```powershell
.\run_suite.ps1
```

交接包内已包含六份工作簿时，直接重跑而不重新生成Excel：

```powershell
.\run_handoff_suite.ps1
```

## Hybrid 定义

分层 HybridGuard 先用 StructuralGuard 发现局部异常，再比较 North/Central/East/South/West 相同位置的公式结构并形成连续异常组。每个组只抽取首、中、尾代表点（单点组只取自身），调用 FormulaGuard 的解析器、引用模型、编辑距离和公式求值器验证候选修复；验证通过后才把候选传播到整组。它不是 FormulaGuard 官方版本，也不修改上游冻结模型。

## 六工作簿V5实验摘要

| 场景 | StructuralGuard平均AP | FormulaGuard V5平均AP | HybridGuard V5平均AP |
|---|---:|---:|---:|
| 稀疏单点（3次） | 0.6614 | 1.0000 | 0.9936 |
| 连续块/整列（3次） | 0.4392 | 0.1893 | 0.9717 |

V5非常适合稀疏单点排名；对于本实验的大面积一致错误，单独V5仍无法覆盖大部分组内单元格。Hybrid通过跨平行表连续组共识补足这部分，在3次系统性实验中生成了5,648/5,648个正确修复公式。
