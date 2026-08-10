# FormulaGuard 数据来源与使用协议

本文件是数据证据链的唯一入口。任何进入论文主实验的数据集都必须在此登记来源、用途、标签类型、许可/下载状态和排除规则。

## 1. 主数据：PropagationBench-Synthetic

- 来源性质：本研究自行生成的合成基准，不伪装成真实业务数据。
- 生成方式：10 个工作簿模板族；开发2族、验证2族、最终测试6族，按模板族物理隔离；使用固定随机种子生成公式、输入值和六类错误。
- 真值：生成器同时保存正确公式、错误公式、源单元格、依赖路径、预期传播深度和随机种子。
- 主要用途：主定位对比、传播深度实验、消融、修复候选、性能实验。
- 必须验证：能重算、无显式错误码、至少一个汇总输出改变、至少两个下游公式受影响、恢复正确公式后结果恢复。
- 风险控制：训练/开发/测试按模板族隔离，不把同一模板的不同参数版本随机拆开。
- 标签隔离：公开实例路径写入 `instances.jsonl`，源错误、正确公式和目标输出单独写入 `evaluation_labels.jsonl`；定位算法只读取工作簿。
- 引用方式：引用本项目代码版本、生成器配置和数据清单，不声称外部真实来源。

## 2. 真实错误：Enron Error Corpus

- 官方介绍：https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/enron-error-corpus/
- 事实：公开页面说明该错误语料从 Enron 工作簿中识别出 36 个真实错误，并提供标记错误单元格的 properties 文件。
- 主要用途：真实错误外部验证和案例分析。
- 纳入条件：文件可合法下载；公式语法在本项目支持范围；错误位置与修复可确认；工作簿可在隔离环境打开。
- 排除条件：宏/外部链接为核心依赖、文件损坏、错误标签无法对应当前文件、多个源错误无法拆分、仅显式运行时错误且不符合主任务。
- 报告要求：公开总数、下载成功数、语法可支持数、最终纳入数和逐项排除原因。

## 3. 注入错误与测试判定：Modified EUSES Corpus

- 总览：https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/corpora-overview/
- 规模与性质说明：https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/corpora-comparison/
- 公开统计：比较页给出 EUSES 基准含 184 个基础工作簿、576 个故障版本；公式规模从 6 到 10,316 个，复制公式比例较高。
- 主要用途：在取得并确认许可/格式后，用作第二个外部故障定位基准；也可用于与 SFL-Oracle 对比。
- 限制：其错误为人工注入且测试判定依赖正确版本，不能作为“真实自然错误”的证据。
- 当前状态：待下载与格式审计，不进入第一轮快速实验。

## 4. 修复补充：FoRepBench

- 论文：https://kdd-eval-workshop.github.io/genai-evaluation-kdd2025/assets/papers/Submission%2033.pdf
- 数据仓库：https://github.com/microsoft/prose-benchmarks/tree/main/FoRepBench
- 公开事实：论文报告生成 1,095 个样本，其中 618 个通过验证；任务集中在 `#DIV/0!`、`#N/A`、`#NAME?`、`#REF!`、`#VALUE!` 等显式运行时错误。
- 主要用途：候选公式生成模块的补充测试。
- 不进入主定位结果的原因：其错误类型主要是显式运行时错误，不等同于本项目的静默数值错误与源错误定位。

## 5. 真实复杂工作簿压力测试：SpreadsheetBench

- 项目页：https://spreadsheetbench.github.io/
- 仓库：https://github.com/RUCKBReasoning/SpreadsheetBench
- 公开事实：V1 含 912 个真实论坛任务及 2,729 个测试文件，覆盖复杂、多表和非标准布局。
- 主要用途：解析鲁棒性、运行时间和“无法支持时是否安全跳过”的压力测试。
- 不进入主准确率的原因：它不是带源错误标签的公式根因定位数据集。

## 6. 数据分层与论文表述

| 层级 | 数据 | 可支持的结论 |
|---|---|---|
| A 主实验 | PropagationBench-Synthetic | 因错误和传播深度受控，可做因果比较和消融 |
| B 外部验证 | Enron Error Corpus | 检验真实错误可用性，但样本量较小 |
| C 扩展验证 | Modified EUSES | 检验跨工作簿结构的泛化并提供有真值辅助参考 |
| D 补充/压力 | FoRepBench、SpreadsheetBench | 仅支持修复或解析鲁棒性结论 |

论文不得把 A 层描述为真实业务数据，不得把 D 层结果混入静默根因定位主指标。

## 7. 数据审计产物

每次数据构建必须生成：

1. `dataset_manifest.json`：数据版本、生成时间、种子和文件哈希；
2. `instances.jsonl`：每个错误实例的真值和验证状态；
3. `exclusions.csv`：公开语料排除原因；
4. `dataset_summary.csv`：模板族、错误类型、深度、公式规模分布；
5. `LICENSES_AND_TERMS.md`：公开语料许可、引用要求和下载日期。
