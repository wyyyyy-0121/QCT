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

### SpreadsheetBench 2

- 论文：<https://arxiv.org/abs/2606.29955>
- 数据：<https://huggingface.co/datasets/KAKA22/SpreadsheetBench-v2>
- 代码：<https://github.com/RUCKBReasoning/SpreadsheetBench-2>
- 公开规模：321 个端到端任务，其中 100 个 Debugging；每个 Debugging 输入不在指令中
  公布错误类型或目标格，金标准工作簿可机械定义需修改格。
- 许可：论文正文声明数据 CC BY-SA 4.0、代码 MIT；数据卡顶层 MIT 标记与正文冲突，
  本项目按更严格的数据许可处理，不再分发原始工作簿。
- DRFV 用途：100 个 Debugging 任务完整保留为候选冻结和预测锁后的外部公式源格测试，
  不用于训练或调参；专家注入错误不能被描述为自然发生错误。
- 固定 revision、接收隔离和停止门见
  `research/V5_DRFV_MECHANISM_SELECTION_AND_PREREGISTRATION.md`。

## 4. 数据证据分层

| 层级 | 数据 | 可以支持的结论 |
|---|---|---|
| A 主实验 | PropagationBench-v2 Synthetic | 在受控错误、深度和拓扑上的定位、修复、消融与因果比较 |
| B 外部验证 | Enron Error Corpus | 对真实错误可用性的有限验证 |
| C 扩展验证 | Modified EUSES | 跨工作簿结构与注入故障的补充泛化证据 |
| D 补充/压力 | FoRepBench、SpreadsheetBench | 修复或解析鲁棒性，不支持静默根因主结论 |

论文不得把 A 层描述为真实业务数据，不得把 D 层结果混入静默根因定位主指标。

## 4.1 V6 新证据层（与旧 PropagationBench 隔离）

V6 不复用已揭晓 100 例做选择。其内部数据由
`scripts/build_v6_dataset.py` 新建：开发 1,200、锁定内部验证 360、干净控制
240、安全红队 360。六类错误、五种拓扑、四档复杂度及三档实算传播深度均由
审计脚本从实际 XLSX 重新验证。公开 `instances.jsonl` 不含源单元格、错误类型、
正确公式或预期深度；这些字段只在 `evaluation_labels.jsonl` 中，由排序完成后的
评分程序读取。

最终 600 例由第三方在项目外从至少 30 个未见、可合法使用的真实模板制作，
每类 100 例。480 例可由第三方自己的程序化流程产生，另外每类 20 例、共
120 例必须有真实人工或半人工修改及复核记录。项目中的最终打包器不会调用
内部合成生成器，只验证第三方提交的原表/错误表对并打包。冻结前只公开标签、
例外表和 SECRET.zip 的 SHA-256；冻结后释放无标签 PUBLIC.zip，预测锁后释放
SECRET.zip。该集合才是 V6 的最终独立证据。完整协议见
`research/V6_THIRD_PARTY_PROTOCOL.md`。

## 4.2 V5-PSL-dev1 公开压力层与独立确认层

V5-PSL不再把同源合成生成器的高分当作晋级依据。公开压力层固定为六个来源，
其注册表是`data/external/v5_psl/corpus_registry.json`：

| 数据 | 固定版本 | 只允许的用途 |
|---|---|---|
| Modified EUSES | `EUSES_modified.zip`, SHA-256 `3701d4d3...c3d4` | 已揭晓注入故障开发与控制压力 |
| Info1 | `Info1.zip`, SHA-256 `b889174a...f9e3` | 已揭晓真实故障回顾性开发 |
| Integer Corpus | `Integer.zip`, SHA-256 `47d6950a...9aec` | 整数域注入故障压力 |
| Enron Error Corpus | `Error_ENRON.zip`, SHA-256 `4f23c7cb...4450` | 已揭晓真实错误安全回归 |
| FoRepBench | Git `d17e278092c59ec6faaa2d88730bdcbe48bb95f2` | 618项显式错误修复公式对；定位准确率为0项 |
| SpreadsheetBench | Git `49b73a94775fb489063f60ca1865e3a650079a79` | 复杂XLSX解析、无标签诊断和有记录拒绝 |

前三个SFL语料使用工作表序号坐标和旧`.xls`格式。适配器只保留原始坐标和哈希，
不会自动猜工作表名；转换、单/多源可识别性和纳入决定必须人工复核。FoRepBench和
SpreadsheetBench有专用角色审计，硬性禁止把其修复/操作标签计入静默源定位指标。
许可不清的数据只在本地使用，原始文件统一位于Git忽略的
`data/external/v5_psl/raw/`。

公开压力结果仍是已揭晓开发证据，只允许一次有根因、证据哈希和源码提交记录的
机制修订。候选锁前还必须完成主论文核对；模板中的`passed=false`不能手工当作通过
回执。

锁定确认协议v2由一名未参与开发的独立保管评测人准备并盲持：30个未见模板，
240错误和120控制；其中180个可识别错误、60个歧义错误、60普通控制和60合法例外
控制。保管人在候选锁前只公布PUBLIC与SECRET归档哈希；候选锁后释放无标签PUBLIC，
完整排名锁后才释放SECRET并评分一次。该设计不提供多制题人或标注者一致性证据，
只能称为单保管人盲持的外部模板确认。原始数据和当前仓库中都没有这360例，因此
当前不能报告锁定确认结果或使用`V5-R1`名称。

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
