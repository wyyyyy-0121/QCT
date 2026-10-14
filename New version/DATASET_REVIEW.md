# 数据集核查

日期：2026-10-14

本轮重新调查的目标是找到能评价“静默源公式错误定位和修复”的数据。下载包已做 ZIP CRC、配置文件引用、工作簿路径和公开 Git blob 核对。当前只完成下载和审计，尚未转换、配对、运行模型或获得新数据成绩。

## 1. 可用性总览

| 数据 | 当前实查规模 | 标签内容 | 当前用途判断 |
|---|---:|---|---|
| Enron Error Corpus | 36 个事件，30 个预纳入事件，25 个唯一工作簿 | 源错误单元格；没有完整正确公式 | 回顾性定位回归，不计算修复精确率 |
| Modified EUSES | 705 个 properties、2,060 个工作簿、705 个源格标签 | 每配置 1 个源格，含故障类型 | 主候选，先核对官网数量差异和原表映射 |
| Info1 | 119 个 properties、119 个工作簿、5,609 个源格标签 | 学生错误，故障类型为空；2 个模板 | 真实学生错误补充，不能当 119 个独立业务家族 |
| Integer | 231 个 properties、312 个工作簿、404 个源格标签 | 整数域注入错误 | 机制补充，先排除非公式源格 |
| Payroll/Gradebook | 349 个 properties、349 个 xls、1,502 个源格标签 | 用户测试判断中有 565 个 `ORACLE_MISTAKE=T` 标记 | 用户判断和约束压力，不作为无噪声真值 |
| FoRepBench | 618 个生成样本，59 个论坛种子 | 正确/错误公式均有，运行时错误均非空 | 显式公式报错修复，不替代工作簿级静默定位 |
| SpreadsheetBench | README 记录 912 指令、2,729 个测试工作簿，另有 400 Verified 描述 | 指令操作输入与答案表 | 工作流或操作补充，不直接提供静默源格真值 |
| SpreadsheetBench 2 | README 有 `Debugging` 分类和 input/golden 路径 | 数据文件本轮未从 Hugging Face 恢复 | 待恢复后核对，暂不称已下载可用 |
| ExceLint | 源码和 README 已核查 | 结构异常定位工具；独立真值尚未核实 | 作为方法对照候选 |

## 2. 已下载文件与审计结果

### Modified EUSES

`archives/EUSES_modified.zip` 的 SHA-256 为 `3701d4d322dc057d166be0aa4104284a701614174ac8f4ab852616df4127c3d4`，ZIP CRC 通过。包内有 705 个 `.properties`、2,058 个 `.xls` 和 2 个 `.xlsx`，705 个配置引用均能找到工作簿，每个配置当前解析到 1 个源格标签。官网页面写的是 184 个基础表、576 个单错误版本，和当前包的实查数量不同；正式实验前要确认下载版本、模板家族、重复版本和原始工作簿映射。

### Info1

`archives/Info1.zip` 的 SHA-256 为 `b889174ac36c7ddc66207dff7e53e831c804802723dcd8b75b04a1f70368f9e3`，包含 119 个配置和 119 个工作簿，源格标签共 5,609 个。标签数量从每表 1 个到 404 个不等，故障类型字段为空。只有 2 个练习模板，分割时必须按模板家族隔离。

### Integer

`archives/Integer.zip` 的 SHA-256 为 `47d6950a9275e68b4b3c51177893b2a9dbc3053243e30b7eb88c32bbc6829aec`，包含 231 个配置、312 个工作簿和 404 个源格标签。README 指出 `FW_fibonacci_3Faults_Fault1.properties` 的 `0!C!12` 不是公式，适配器必须先检查源格类型。

官网记录 33 个基础表，其中 21 个来自真实来源、12 个人工创建。限定整数域的收益只支持整数域结论；312 个归档工作簿不等于 312 个独立模板。

### Payroll/Gradebook

`archives/Payroll_Gradebook.zip` 的 SHA-256 为 `9195fa8f8322285749d28fcf8ade5ae75492639e3a88fda64f46d8fd0ac94042`，包含 349 个配置、349 个 xls 和 1,502 个源格标签。用户测试判断中有 565 个 `ORACLE_MISTAKE=T` 标记；这与源错误标签计数属于不同口径。它有两个基础模板，官网所说的用户判断错误不能直接变成逐单元格正确公式真值。

### 多故障 EUSES

`sources/modified_euses_multi_fault.source` 对应下载包 `EUSES-double-triple-faults.zip`，SHA-256 为 `cd26421c76f0d1b74f35af1ba80ab633ccc98544dfbe7a3743f87d7b4a061ae2`，包含 217 个 properties 和 355 个 xls。它适合测试共享错误、多个源格和耦合搜索，但仍需要配对和原公式核对。

### FoRepBench

固定 ref 为 `d17e278092c59ec6faaa2d88730bdcbe48bb95f2`。`FoRepBenchmarks.json` 有 618 条，`seed_data.json` 有 59 条；两者均提供正确公式、错误公式和非空运行时错误字段。生成数据没有统一的错误公式单元格位置字段，论坛种子有 49 条位置字段。任务输入本身已经给出错误公式和上下文，适合显式运行时报错修复，不能直接当作工作簿级静默错误数据集。

## 3. 标签和许可边界

这些包的 properties 文件没有直接提供可用于静默修复的正确源公式字段。`expected output value` 也不能替代正确源公式。EUSES 和 Integer 含原始目录，后续需要比较原始公式和故障版本，确认每个标注能否生成公式级真值。下载包中未发现统一 license 文件，发布或提交复现包前应单独核对许可和个人信息。

SpreadsheetBench 标注为 CC BY-SA 4.0。FoRepBench 所在仓库的 LICENSE 是多套分项许可清单，不能直接把整个数据集称为 MIT。SpreadsheetBench 2 的数据文件本轮因 Hugging Face 请求超时没有取得，README 和论文只能作为来源记录。

SpreadsheetBench 2 的 `Debugging` 子集可能包含有用的输入/答案配对，取得文件后要核对其是否提供自然静默错误、正确公式和可恢复的源格位置。README 要求实验前重算 input/golden；将来只在转换副本上做重算，并记录 Excel/LibreOffice 版本和公式变化。ExceLint 的源码依赖 F#/C#、Visual Studio 2017 和 Windows Office，目前没有在 WSL 完成运行。

## 4. 推荐的适配顺序

1. 先对 EUSES 单故障和多故障包做原表配对、模板聚类、重复检查和公式保真检查。
2. 再选择少量 EUSES、Integer、Info1 工作簿做人工试标，区分错误公式、正确公式、合法例外和未知公式。
3. 对 `.xls` 只在副本区转换为 `.xlsx`，逐工作簿保存原文件哈希、转换日志、公式数量和公式文本抽样差异。
4. 通过适配器生成独立的 `input`、`label` 和 `clean_control`，检测器运行时不读取 label。
5. 固定按模板家族或近重复簇分割开发与留出集，再锁预测、最后评分。

当前包只证明“数据可以取得并且标注引用完整”，没有证明它们已经具有可用于论文主结论的正确公式真值。

## 5. 来源和核查入口

| 数据或工具 | 官方来源 |
|---|---|
| Enron | <https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/enron-error-corpus/> |
| Modified EUSES | <https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/euses/> |
| Info1 | <https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/info1/> |
| Integer | <https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/integer-corpus/> |
| Payroll/Gradebook | <https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/payrollgradebook-2/> |
| 标注格式 | <https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/format/> |
| FoRepBench | <https://github.com/microsoft/prose-benchmarks/tree/d17e278092c59ec6faaa2d88730bdcbe48bb95f2/FoRepBench> |
| SpreadsheetBench | <https://github.com/RUCKBReasoning/SpreadsheetBench> |
| SpreadsheetBench 2 | <https://github.com/RUCKBReasoning/SpreadsheetBench-2>；<https://huggingface.co/datasets/KAKA22/SpreadsheetBench-v2> |
| ExceLint | <https://github.com/ExceLint/ExceLint> |

本轮官方页面、论文、API 返回、访问失败和下载哈希均保存在 [数据审计目录](20261014_dataset_review/)。[ARCHIVE_AUDIT.json](20261014_dataset_review/ARCHIVE_AUDIT.json) 保存包内计数，[ANNOTATION_INVENTORY.csv](20261014_dataset_review/ANNOTATION_INVENTORY.csv) 保存四个主 ZIP 的 1,404 个配置引用。多故障包当前只完成 CRC 和文件计数审计，尚未逐配置核对其工作簿引用。
