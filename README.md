# FormulaGuard

FormulaGuard 是一个面向高中生竞赛项目的可复现实验原型：在不知道正确输出值的情况下，从 Excel 公式依赖图中定位最可能的静默源错误，并给出候选修复。项目目标是做到本科课程设计级别的完整度，而不是堆成博士论文规模。

## 现在已经有什么

- `.xlsx` 读取、A1公式解析、依赖图和支持公式子集重算；
- 公式族、图结构、行为异常和图干预责任分数 GIR；
- 10类模板族、6类静默错误、浅/中/深传播的可控基准生成器；
- 9个主比较方法、5个消融方法、bootstrap置信区间；
- 干净工作簿警报率、敏感性、性能、失败案例与真实语料评价代码；
- 自动生成 CSV、Markdown 报告、格式化 Excel 结果工作簿和完成度审计。

## 第一次运行

在 Windows `cmd` 中：

```bat
cd /d D:\code\QCT
run_tests.cmd
run_pipeline.cmd smoke -Ablations
```

短测试和 smoke 由 Codex 负责。如果它们通过，用户只需运行首轮大型实验：

```bat
run_pipeline.cmd quick -Ablations -WithSensitivity
```

quick 完成后，由 Codex 审核结果并运行冻结脚本：

```bat
python scripts\freeze_configuration.py --results results\quick --validation data\propagationbench_quick\validation
```

只有生成 `results\quick\frozen_config.json` 后，才能运行最终合成实验和性能实验：

```bat
run_pipeline.cmd full -Ablations -WithSensitivity -WithPerformance -WithLibreOffice
```

不要把 `results\smoke` 的数字写进论文。smoke 只是检查流水线；`quick` 用于改进算法和冻结权重；`full` 会校验冻结配置、代码哈希、Git提交及工作区状态，最终主表只使用冻结后生成的 `full`。

## 运行后看哪些文件

以 quick 为例：

- `data\propagationbench_quick\validation\dataset_quality.json`：数据是否有效、六类错误和深度分布；
- `results\quick\summary.csv`：全部方法的 Top-k、MRR、EXAM、修复率和耗时；
- `results\quick\paired_comparison.json`：FormulaGuard 与最强无真值基线的配对比较；
- `results\quick\by_error.csv`、`by_depth.csv`、`by_family.csv`：分错误、深度和模板结果；
- `results\quick\by_split.csv`：开发/验证分区结果；full 应只出现 `test`；
- `results\quick\clean_summary.json`：干净合成工作簿的警报率；
- `results\quick\failure_cases.csv`：FormulaGuard 落后于最强基线的案例；
- `results\quick\figures\`：由实测 CSV 自动生成的论文 SVG 图；
- `results\quick\demo\demo_case.json`：可复现的Top-5和影响路径演示；
- `results\quick\environment.json`：运行环境、源文件哈希和代码版本；
- `results\quick\pipeline.log`、`result_index.json`：完整命令输出和带哈希的结果索引；
- `results\quick\REPORT.md`：自动生成的文字报告；
- `results\quick\completion_audit.json`：证据文件是否齐全；
- `outputs\FormulaGuard_quick_experiment_results.xlsx`：答辩和作图用工作簿。

## 检查一个自己的工作簿

```bat
diagnose.cmd "D:\你的路径\example.xlsx" --top 10 --json "D:\你的路径\diagnosis.json"
```

算法冻结后，答辩演示增加 `--config results\quick\frozen_config.json`，保证现场诊断使用的权重与 full 正式实验完全一致。

这个命令不需要正确答案，只会给公式单元格排序和候选修复。当前支持范围见 `research\METHOD_SPEC.md`；宏、外部链接、结构化引用、动态数组和大量高级函数暂不支持。

运行完 quick 后可以直接生成/查看三分钟演示案例：

```bat
run_demo.cmd quick
```

## 真实语料外部验证

先按 `data\external\README.md` 下载并整理 Enron Error Corpus。准备好 `manifest.csv` 后运行：

```bat
run_external.cmd "data\external\enron\manifest.csv" "results\enron"
```

真实语料结果必须与合成结果分表报告，不能把未支持、损坏或标签不清的文件悄悄删除；逐项记录排除原因。

## 环境

核心 Python 代码和单元测试只使用 Python 3.11+ 标准库，不需要安装额外 Python 包。工作簿生成和结果工作簿使用 Codex Desktop 随附的 `@oai/artifact-tool`。一键脚本会优先寻找 Codex 随附的 Python、Node 和模块，找不到时再使用系统安装。

## 研究纪律

- 错误位置和正确公式只用于离线评价，不能传给 FormulaGuard。
- ExceLint-like、WARDER-like 和 Behavior-like 是思想级透明复现，不冒充原作者官方实现。
- 所有论文数字由输出 CSV 生成，不手工改表。
- 置信区间跨过0时，不写“显著优于”。
- 数据来源、论文结构和正式方法分别见 `research\DATA_SOURCES.md`、`research\PAPER_ARCHITECTURE.md`、`research\METHOD_SPEC.md`。
