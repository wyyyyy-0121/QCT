# FormulaGuard

FormulaGuard 是一个面向高中生科研竞赛的可复现实验原型：在不知道正确输出值的情况下，从 Excel 公式依赖图中定位最可能的静默源错误，并给出候选修复和传播路径。项目目标是本科课程设计级别的完整研究，而不是堆成研究生或博士论文规模。

## 研究主线

1. 把公式单元格及引用关系转换为有向依赖图；
2. 计算公式族、图结构、数值行为和内部一致性异常；
3. 从邻近公式和平移/小编辑生成候选修复；
4. 临时替换候选并重算工作簿，测量异常能量下降；
5. 用图干预责任分数GIR输出Top-5源错误、修复建议和影响路径。

正确公式和源错误标签只用于离线评价，不传给定位器。

## 当前版本

- v1：已冻结并完成864例full，保留为工程基线；其测试族结构重复，不作为最终跨结构结论。
- v4-r1：当前冻结模型；代码、配置和历史证据保持不变。
- v5-pcg-r1：开发候选。它只在Pattern精英、强反事实证据和“V4名次低于Top-5”三者同时成立时启用联合救援，否则严格回退V4。

研究设计、方法和数据说明：

- `research\METHOD_SPEC.md`
- `research\EXPERIMENT_PROTOCOL.md`
- `research\DATA_SOURCES.md`
- `research\PAPER_ARCHITECTURE.md`
- `PROJECT_STATUS.md`

## 你和Codex的分工

Codex负责：单元测试、smoke、结构检查、单工作簿诊断、候选检查、CSV/报告/Excel审计、失败定位和短代码修改。

用户只负责：Codex明确通知的大型quick、full、敏感性、性能、LibreOffice和Enron批量实验。大型运行后不必粘贴长日志，只需告诉Codex“运行完成”或最后一段错误信息。

## 短测试（由Codex运行）

```bat
cd /d D:\code\QCT
run_tests.cmd
run_pipeline.cmd smoke -BenchmarkVersion v2 -Ablations
```

smoke只检查工程链路，不写入论文主结论。

V5的62项单元、协议和真实性测试，以及单错误表、单干净表工程smoke均由Codex运行；用户不需要重复执行。

## V5唯一完整开发运行

V5方法在 `research\V5_METHOD_SPEC.md` 预登记；工程smoke引出的唯一一次必要性修订单独记录于
`research\V5_METHOD_SPEC_AMENDMENT_1.md`。18例合成数据对V5是开发数据，不重新称为盲测。

只有Codex确认源码已提交后，用户运行：

```bat
cd /d D:\code\QCT
run_v5_development.cmd
```

该命令只新算V5，并复用已锁定的V4及基线逐事件结果；依次检查18例合成开发集、30例Enron安全回归和48份干净工作簿。任一预登记门槛失败即否决V5，不在同一数据上继续调参。全部通过后才允许冻结，并仍需一组冻结后新建的独立自然风格验证集。

## 第一次大型v2实验

只有在Codex确认短测试通过并要求提交代码后，用户才运行：

```bat
cd /d D:\code\QCT
run_pipeline.cmd quick -BenchmarkVersion v2 -Ablations -WithSensitivity
```

流水线默认使用约75%的逻辑处理器。在32线程机器上通常是24个工作进程；可用 `-Workers 16` 手动限制。FormulaGuard不训练神经网络，也没有适合GPU的大矩阵批处理，所以GPU空闲是正常现象，性能主要来自CPU多进程和减少重复求值。

quick会生成：

- `results\v2_quick\summary.csv`：主指标；
- `paired_comparison.json`：与最强无真值基线的配对比较；
- `by_error.csv`、`by_depth.csv`、`by_family.csv`：分层结果；
- `clean_summary.json`：干净表报警与召回；
- `sensitivity_summary.csv`：三组预登记权重和候选数；
- `completion_audit.json`：证据完整度；
- `outputs\FormulaGuard_v2_quick_experiment_results.xlsx`：查看与答辩用工作簿。

## 冻结与正式实验

Codex审核quick通过后生成：

```bat
python scripts\freeze_configuration.py --results results\v2_quick --validation data\propagationbench_v2_quick\validation
```

冻结文件保存权重、报警阈值、候选数、Git提交和核心文件哈希。v2 full会拒绝缺少冻结文件、代码变化或未提交工作区，防止看完正式测试结果后再调参。

冻结完成后，用户运行：

```bat
run_pipeline.cmd full -BenchmarkVersion v2 -Ablations -WithSensitivity -WithPerformance -WithLibreOffice
```

## 诊断自己的工作簿

```bat
diagnose.cmd "D:\你的路径\example.xlsx" --top 10 --json "D:\你的路径\diagnosis.json"
```

该命令不需要正确答案，只输出可疑公式、候选修复和证据。正式答辩演示应增加冻结配置，确保与论文实验一致。

## Enron真实语料

按 `data\external\README.md` 准备 Enron Error Corpus 和 `manifest.csv` 后运行：

```bat
run_external.cmd "data\external\enron\manifest.csv" "results\enron"
```

所有36项都要清点；不支持、损坏或标签不清的文件逐项记录排除原因。真实和合成结果分开报告。

## 环境与Git

核心Python代码和单元测试使用Python 3.11+标准库。工作簿生成和结果工作簿使用Codex Desktop附带的Node运行环境。LibreOffice只用于独立批量重算与交叉验证，不参与FormulaGuard定位。

`quick` 和 `full` 启动时会检查Git：已跟踪文件必须全部提交，运行结束时提交号不能变化。`results`、`outputs`和生成的基准文件默认忽略，不进入源码提交。

## 研究纪律

- 不把合成数据写成真实业务数据；
- 不把内部一致性检查写成实验真值；
- 不把ExceLint-like、WARDER-like写成原作者官方实现；
- 不把smoke、topology或sparse探针数字写成正式主结论；
- 置信区间跨0时不写“稳定优于”；
- full完成后不再调整模型权重或报警阈值；
- 所有论文数字和图表从原始CSV自动生成。
