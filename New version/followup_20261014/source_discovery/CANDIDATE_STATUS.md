# 新来源候选状态

2026-10-18状态更正：Iowa State、Damodaran、EPA、英国政府、18F、Packt和Renewables七个来源已经用于dev7/dev10开发，整个来源均排除最终验证；SOURCE_READINESS.json已据11个实际输入及哈希修正。下文是历史发现记录，其中“未下载”“待查候选”不能继续当作未见来源证明。最终合格来源/家族仍为0。

这里只审查来源元数据和公开目录，不含最终验证工作簿或逐项答案。候选多不等于合格来源多；尚未满足六来源十五家族。

2026-10-15增量审计见 `SOURCE_READINESS.json`、`metadata_v3/RECEIPT.json`至`metadata_v5/RECEIPT.json`。18F已直接核实CC0；Packt固定commit的MIT正文已读取；Renewables README声明CC BY-NC-SA 4.0，但固定tree无LICENSE。EPA官方计算表/勘误及英国TAG、DESNZ LCOE入口已核实，仅为待查候选。以下表格保留较早发现记录，以新台账为当前状态。合格来源与家族数仍为0。

| 候选 | 可能用途 | 实查及未解决问题 |
|---|---|---|
| Damodaran 官方模型目录 | 公开工作簿注入 | 官方页可访问，包含多类 xls/xlsx 链接；需核查许可、模板差异和原公式，不假定干净 |
| 18F/financial-models | 公开工作簿注入 | 固定 Git commit 目录含 Software Model.xlsx；许可标记 NOASSERTION，需读原条款 |
| PacktPublishing 项目融资教程 | 公开工作簿注入 | 目录含 Financial+Model.xlsx，仓库标记 MIT；需确认数据条款和公式真值 |
| RenewablesPro/rvi-sample-models | 公开工作簿注入 | 目录有样例模型；没有 API 识别许可，待查 |
| edencj95/excel-LCOE-model | 公开工作簿注入 | 目录有两个能源模型；可能只有一个模板家族，许可待查 |
| tylerjsteffensen/solar_project_finance | 公开工作簿注入 | 目录有 Solar_Plus_Storage_PF_Model.xlsx；许可及模型来源待查 |
| sambhavu/XLSX | 公开工作簿注入 | 目录32个工作簿；多个表可能复制其他作者，不能直接视为独立来源或32家族 |
| Reinhart–Rogoff 历史复现 | 自然错误候选 | HAP-RR-git标记CC0并含两个工作簿；复现仓库不等于保留错误原表与可靠正确公式，尚未证明可评分修复；同案例不同镜像只算一源 |
| SpreadsheetBench 2 | 调试任务候选 | README有Debugging/input/golden契约，仓库无工作簿；与已用v1的来源关系未厘清，按整体来源排除原则暂不纳入 |
| Spreadsheet Error Dataset / Tasi | 排除 | README说明工作簿来自EUSES，是已用来源的衍生，不可计新源 |
| SpreadNaLa | 待查 | 公式生成与静默错误修复任务不同，不计主验收来源 |

访问失败也保留在回执：旧Damodaran链接404、NREL域名解析失败、World Bank页面403、部分raw README超时。目录清单固定仓库commit；尚未下载候选XLSX，不根据目标模型能否做对来筛选工作簿。
