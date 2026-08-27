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
- V4.1-PCG（历史代码名v5-pcg-r1）：直接重排实验已被否决；它在Enron安全回归中使MRR低于V4。
- V4.2-Review-B（历史代码名v5.2-B）：冻结的安全辅助审查位，不改变V4 Top-5。
- V4.3-Semantic（历史代码名v6）：FFC/BSS语义重排机制实验；定位机制有效，但未通过正确表格误报等冻结门槛。
- V5-Core：候选中心的多证据责任主排序器；不调用`v4_scores()`取得基础排名，当前已完成核心实现、数据协议、锁定评测和短测试框架，尚未经过240例pilot及后续大型验证。

正式命名、历史目录和复现别名的完整映射见
`research\VERSION_LINEAGE_AND_NAMING_POLICY.md`。旧源码、冻结配置和结果目录保持原名，
避免破坏预测锁与SHA-256。

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

V5-Core 的工程 smoke 命令为：

```bat
run_v5_core_smoke.cmd --workers 24
```

它覆盖24个错误工作簿、24份干净控制、V4/V4.3对照、规则头与学习头、候选覆盖、标签隔离，以及Markdown/CSV/XLSX证据导出。该结果只用于工程验收。

## V5-Core 大型实验（由用户运行）

必须按顺序执行；Codex检查上一阶段结果后才进入下一阶段：

```bat
run_v5_core_pilot.cmd --workers 24
run_v5_core_development.cmd --workers 24
run_v5_core_validation_lock.cmd --workers 24
run_v5_core_validation_score.cmd
run_v5_core_freeze.cmd
run_v5_core_performance.cmd --workers 24
run_v5_core_blind_lock.cmd --workers 24
run_v5_core_blind_score.cmd
```

预测阶段与评分阶段物理分离；锁定预测完成前，评分脚本不得读取验证标签。冻结前的开发和内部验证结果不能作为第三方独立结论。
第三方600例必须在仓库外准备，附独立出题声明，并在冻结前只公布哈希；具体输入格式、真实性复核和分阶段交付见 `research/V5_CORE_THIRD_PARTY_PROTOCOL.md`。

V4.1-PCG（历史代码名V5）的62项单元、协议和真实性测试，以及单错误表、单干净表工程smoke均由Codex运行；用户不需要重复执行。

V4.3-Semantic（历史代码名V6）的短测试由Codex运行：

该机制实验已经完成并按预注册门槛停止；以下`run_v6_*`名称是不可改写的历史
复现入口，不代表当前仍存在一个独立“第六代”正式模型，也不应继续用于调参。

```bat
run_tests.cmd
run_v6_smoke.cmd
```

用户只在收到通知后依次运行三个大型开发轮次：

```bat
run_v6_round.cmd a --workers 24
run_v6_round.cmd b --workers 24
run_v6_round.cmd c --workers 24
```

三轮全部完成后才运行一次性内部验证与选择：

```bat
run_v6_validation.cmd --workers 24
```

只有选择回执允许冻结时，才运行 `run_v6_freeze.cmd`。冻结并推送
`v6-lock` 后才接收第三方 PUBLIC.zip，运行 `run_v6_blind_lock.cmd --workers 24`；
锁成功后才能接收 SECRET.zip 并运行 `run_v6_blind_score.cmd`。性能实验使用
`run_v6_performance.cmd --workers 24`。V6 的完整方法和第三方交接边界见：

- `research\V6_METHOD_SPEC.md`
- `research\V6_THIRD_PARTY_PROTOCOL.md`

V6 的实验事件总账为：内部开发/验证/红队/干净控制 2,160，既有 Enron
回顾性事件 30，最终第三方独立集 600，共 2,790；已揭晓的 100 例不计入
V6 选择或验证。第三方 final 打包模式只接受项目外已经制作好的工作簿对，
不会用本仓库生成器冒充独立或半人工数据。

## V4.1-PCG开发运行记录（历史目录V5）

V4.1方法以历史名称V5在 `research\V5_METHOD_SPEC.md` 预登记；工程smoke引出的唯一一次必要性修订单独记录于
`research\V5_METHOD_SPEC_AMENDMENT_1.md`。18例合成数据对V5是开发数据，不重新称为盲测。

V5完整运行已经结束，未通过冻结门槛。命令保留用于复现实验，而不是重复调参：

```bat
cd /d D:\code\QCT
run_v5_development.cmd
```

该命令只新算V5，并复用已锁定的V4及基线逐事件结果；依次检查18例合成开发集、30例Enron安全回归和48份干净工作簿。V5在合成和干净表门槛通过，但Enron MRR未达标且显著低于V4；因此按预登记停止规则停止V5-R2。

## V4.2-Review非干扰救援开发（历史目录V5.2）

V4.2-Review（历史名称V5.2）保留冻结V4完整排名，只允许在Top-5之外附加一个独立的第六审查位。A/B/C三轮机制已同时预登记，必须全部运行后才能选择，不会因A轮门槛失败就另开版本：

```bat
cd /d D:\code\QCT
run_v52_development.cmd a 24
run_v52_development.cmd b 24
run_v52_development.cmd c 24
run_v52_select_and_freeze.cmd
```

只有前三轮审计均存在、至少一个版本通过全部硬门槛且产生至少2个开发集新增救援命中时，最后一条命令才会生成`research\frozen_config_v52.json`。开发数据均为已揭晓或回顾性数据，不能写成新盲测。

冻结并提交后，由独立出题人只提供15份无标签公开工作簿，运行：

```bat
run_v4_v52_blind_lock.cmd --workers 24
```

看到联合预测锁成功后才接收项目目录外的标签，再运行`run_v4_v52_blind_score.cmd`。详细交接要求见`research\V4_V52_INDEPENDENT_HANDOFF.md`。

扩展 100 例合并集（其中 15 例为既有 Cohort-1，85 例为新 Cohort-2）使用：

```bat
run_v4_v52_blind_100_lock.cmd --workers 24
```

成功生成新锁文件后才允许释放 Batch-2 标签，再运行
`run_v4_v52_blind_100_score.cmd`。哈希承诺与证据边界见
`research\V4_V52_INDEPENDENT_100_PROTOCOL.md`。

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
