# HybridGuard V5 交接说明

## 交接版本

- 项目版本：`0.3.0`
- 交接日期：`2026-09-04`
- FormulaGuard活动模型：`v5-formulaguard-silent-source-r1`
- Python要求：3.11及以上
- 已验证环境：Windows 11、Python 3.12.13、Intel i7-13620H、39.7 GiB RAM

## 已确定的模型分工

| 组件 | 职责 | 不承担的职责 |
|---|---|---|
| StructuralGuard | 快速全表扫描、局部异常、连续块边界 | 不负责展开整列全部错误 |
| FormulaGuard V5 | 稀疏单点排名、局部语义证据、候选公式 | 不单独承担大面积组内覆盖 |
| 跨表多数共识 | 连续块和整列的组级定位 | 不适用于缺少可比平行表的工作簿 |
| HybridGuard | 合并局部证据和组级证据；代表点验证后传播修复 | 不绕过验证自动修改原工作簿 |

## 快速开始

在交接包根目录执行：

```powershell
python -m pip install -e .
.\run_handoff_suite.ps1
```

上述命令使用 `workbooks/` 中已有的六份Excel，不需要Node或Codex私有依赖。运行结果写入 `rerun_results/`。

单文件运行：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m hybridguard.runner_hierarchical `
  workbooks\sparse_seed101.xlsx `
  workbooks\sparse_seed101_truth.json `
  --output-dir rerun_results\sparse_seed101
```

## 目录结构

- `src/hybridguard/`：融合、代表点验证、运行和汇总代码。
- `src/structuralguard/`：StructuralGuard实现。
- `src/formulaguard/`：FormulaGuard基础模块和V5实现。
- `tests/`：单元测试。
- `workbooks/`：六份75,000格测试Excel及独立答案键。
- `results/`：已完成的六轮V5实验结果和汇总报告。
- `scripts/`：重新生成合成工作簿的脚本；生成脚本依赖Codex内置的`@oai/artifact-tool`，日常复跑无需使用。
- `vendor/`：第三方许可证。

## 已验证结果

- 稀疏场景：FormulaGuard V5三次平均AP `1.0000`；Hybrid `0.9936`。
- 系统性场景：FormulaGuard V5三次平均AP `0.1893`；Hybrid `0.9717`。
- Hybrid生成正确修复：稀疏 `102/102`，系统性 `5648/5648`。
- 单份75,000格端到端时间：`31.67–42.12秒`。
- 单份峰值内存：`158.21–219.01 MiB`。
- 五项单元测试全部通过。

## 重要边界

六份工作簿是固定随机种子的合成数据。系统性高分依赖至少三张结构可比的平行工作表；不能直接外推到单表、多个平行表同时以相同方式出错或高度异构的真实工作簿。答案键只用于运行结束后的评分，不进入检测模型。

## 来源

完整来源和许可说明见 `ATTRIBUTION.md`。用户提供的V5源文件记录SHA-256为：

`26ee27bfc93366fc0001dda680fd8e55a51a42e935d5fba955d89e3e754e347b`
