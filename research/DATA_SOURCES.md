# FormulaGuard 数据来源、标签与使用边界

本文档是项目数据证据链的入口。进入论文的每个数据集都必须登记来源、用途、标签性质、许可或使用条款、下载状态和排除规则。

## 1. 主数据：PropagationBench-v2 Synthetic

### 1.1 来源性质

这是本研究自行编程生成的合成基准，不是真实企业数据，也不声称代表真实错误的自然频率。它的用途是控制错误类型、传播深度和依赖拓扑，以便做可重复的因果比较。

生成器为 `scripts/build_benchmarks_v2.mjs`。固定种子方案、文件哈希、模板族、拓扑、版本、错误类型和数据划分写入 `dataset_manifest.json`。

### 1.2 十个模板族与六类拓扑

| 数据划分 | 模板族 | 依赖拓扑 |
|---|---|---|
| development | budget_tree | hierarchical_tree |
| development | sales_timeline | horizontal_chain |
| validation | inventory_flow | multi_sheet_cascade |
| validation | grade_matrix | matrix_hub |
| test | experiment_pipeline | multi_sheet_cascade |
| test | energy_series | rolling_vertical |
| test | schedule_chain | horizontal_chain |
| test | invoice_tree | hierarchical_tree |
| test | attendance_matrix | matrix_hub |
| test | fundraising_branches | fork_join |

正式测试的六个族在业务表面名称、公式布局、方向、工作表数量、跨表引用和分叉/汇合方式上均有区别。`audit_structural_diversity.py` 不相信生成器声明，而是从实际 XLSX 重建图并计算结构签名。

### 1.3 可见与困难版本

偶数版本保留额外的局部同类公式，代表复制规律较清楚的条件；奇数版本移除这些邻居，代表局部证据稀疏的困难条件。v2 full 的八个版本各含四个可见版本和四个困难版本。

### 1.4 内部一致性检查不是实验真值

每份工作簿含 `Checks` 工作表，对浅、中、深三个关键结果做独立重算，并计算两条路径之差。它相当于表格作者主动加入的校验关系，属于工作簿本身可见的数据冗余；FormulaGuard 和所有无真值基线都可以读取。

这些检查不包含“哪个单元格错了”或“正确公式是什么”，不能与 `evaluation_labels.jsonl` 混淆。论文必须将它描述为内部一致性约束，而不是输出真值。

### 1.5 标签隔离

- `instances.jsonl`：公开实例ID、工作簿路径、族、拓扑、版本、错误类型和预期深度；
- `evaluation_labels.jsonl`：源错误单元格、正确/错误公式、受影响输出和真实传播信息；
- 定位程序只读取工作簿；
- 评价脚本在排序结束后读取标签计算指标；
- `SFL-Oracle` 单独使用失败输出标签，不能与无真值方法混为一组。

### 1.6 规模与用途

- smoke：12例，仅做工程检查；
- topology/sparse：各36例，仅做结构和困难条件诊断；
- quick：48例和8份干净表，用于开发、阈值校准和冻结；
- full：864例和48份干净表，用于最终合成主实验。

旧版 PropagationBench-v1 的 full 结果虽有864例，但核心图结构重复，只保留为历史工程基线，不进入最终主结论。

## 2. 真实错误：Enron Error Corpus

- 官方介绍：<https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/enron-error-corpus/>
- 已登记事实：公开页面报告从 Enron 工作簿中识别出36个真实错误，并提供标记错误单元格的 properties 文件；正式写作前需再次核对下载内容和引用信息。
- 用途：真实错误外部定位验证与案例分析；合成和真实结果分别报告。
- 纳入条件：可合法获取；文件可打开或可通过 LibreOffice 无损转换；标签能对应当前文件；公式语法在本项目支持范围；错误符合公式定位任务。
- 排除条件：文件损坏；标签无法对应；宏或外部链接是核心依赖；多源错误无法拆分；只有显式运行时错误且偏离主任务。
- 审计要求：从全部36项开始清点，逐项记录下载、转换、支持、纳入或排除原因。正确公式未知时只评价定位，不评价修复。
- 报告规则：最终支持样本不少于15个时报告定量统计；不足15个时只作为探索性案例研究。

## 3. 可选扩展数据

### Modified EUSES Corpus

- 入口：<https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/corpora-overview/>
- 用途：取得并确认许可、格式和标签后，可作第二外部故障基准或 SFL 辅助比较。
- 限制：其错误多为人工注入，不能当作真实自然错误证据。
- 当前状态：未下载，不进入第一轮正式实验。

### FoRepBench

- 论文：<https://kdd-eval-workshop.github.io/genai-evaluation-kdd2025/assets/papers/Submission%2033.pdf>
- 数据：<https://github.com/microsoft/prose-benchmarks/tree/main/FoRepBench>
- 用途：候选修复模块的补充测试。
- 限制：任务主要覆盖 `#DIV/0!`、`#N/A`、`#NAME?`、`#REF!`、`#VALUE!` 等显式错误，不等同于本文的静默源错误定位。

### SpreadsheetBench

- 项目：<https://spreadsheetbench.github.io/>
- 仓库：<https://github.com/RUCKBReasoning/SpreadsheetBench>
- 用途：复杂、多表和非标准布局的解析鲁棒性及安全跳过压力测试。
- 限制：它不是带源错误标签的根因定位数据集，不进入主准确率。

## 4. 数据证据分层

| 层级 | 数据 | 可以支持的结论 |
|---|---|---|
| A 主实验 | PropagationBench-v2 Synthetic | 在受控错误、深度和拓扑上的定位、修复、消融与因果比较 |
| B 外部验证 | Enron Error Corpus | 对真实错误可用性的有限验证 |
| C 扩展验证 | Modified EUSES | 跨工作簿结构与注入故障的补充泛化证据 |
| D 补充/压力 | FoRepBench、SpreadsheetBench | 修复或解析鲁棒性，不支持静默根因主结论 |

论文不得把 A 层描述为真实业务数据，不得把 D 层结果混入静默根因定位主指标。

## 5. 每次数据构建必须保留的审计产物

1. `dataset_manifest.json`：数据版本、生成时间、种子、结构声明和文件哈希；
2. `instances.jsonl`：公开实例信息；
3. `evaluation_labels.jsonl`：隔离的离线评价标签；
4. `clean_manifest.json`：干净工作簿清单；
5. `dataset_summary.csv`：族、拓扑、错误类型、深度和版本；
6. `validation/dataset_quality.json`：有效率和覆盖检查；
7. `validation/structural_diversity.json`：从实际工作簿计算的结构审计；
8. `exclusions.csv`：公开语料逐项排除原因；
9. `data/LICENSES_AND_TERMS.md`：许可、引用要求和下载日期。
