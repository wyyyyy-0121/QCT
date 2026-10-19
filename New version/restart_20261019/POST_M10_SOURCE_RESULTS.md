# M10后来源核查：新线索未形成可评分自然修订对

本轮独立于模型消融，查提交/仓储元数据并对一条新线索完成公式库存准入。未根据模型表现选来源，没有新增准确率结果。最终合格来源/模板家族仍0/0。

## GitHub修订线索

两条提交查询限定`2023-01-01..2026-10-19`：`"wrong formula" xlsx`报告23条，本页取20条；`"fix formula" ods`报告15条，本页取15条。35个仓库/提交键全部获取文件变更元数据；6个键改动工作簿，其中同一提交在两个仓库镜像重复，不能算独立来源。

| 线索 | 当前证据 | 处置 |
| --- | --- | --- |
| Kartik24Hulmukh两个仓库同一提交 | 新增明确标为故意错误的Excel oracle测试夹具 | 人工故障，不是自然原/修订对；两个仓库不能计两来源 |
| asqd/comma_editor | Excel读取器兼容性提交，新增sales.xls测试夹具 | 软件读写兼容，不认证自然工作簿公式修订 |
| NickAtBishops/GGC | 模板生成脚本修订伴随xlsx变更；仓库API许可null | 缺文件级许可和独立公式真值，不下载工作簿 |
| IRockThs/OOTPResources | Iron Model.xlsx原/修订沿革，作者说投手表有错；仓库API许可null | 保留为未审工作簿候选，不下载、不认证目标、不计来源 |
| kduvekot/ubl-gc | 归档OASIS UBL标准ODS及errata，仓库API许可null | 当前只有标准模型结构/文档变更描述，未建立自然公式故障，不下载工作簿 |

检索与元数据回执为`source_evidence/NATURAL_REVISIONS_POST_M10_20261019.json`、`POST_M10_CANDIDATE_REPOS_20261019.json`。只检查了返回页，不能把总命中数当审阅数，也不声称穷尽搜索。

## DataCite与Mendeley

4个description字段查询均HTTP成功，索引总数分别211、39、8382、230，固定各取前50条（39条查询取全39），共189个唯一DOI。只作题名/描述线索筛查，没有逐条独立审核全部数据集；大量命中为数学公式、软件bug、案例研究或常规“spreadsheet error”文本，不是自然错误数据。完整描述响应保存在忽略目录，公开回执保存查询URL、哈希、题名/许可及本页数量，不把描述全集写入仓库。

定向检查的`10.6084/m9.figshare.6994946.v2`明确为导出汇总时电极数据转置，属于数据值更正；`10.6084/m9.figshare.51032.v1`的“Spreadsheet. Error bars”是图注词语相邻，不是公式修订。Dryad题录中的#REF!错误及“spreadsheet error”类型字段不能自动认证静默公式修复；未下载这几项工作簿。

新线索`10.17632/km8rkfgcpb.1`明确说明控制变量曾有spreadsheet-formula error，且保留published/corrected两列。官方Mendeley页面及DataCite均列CC BY 4.0，版本列表仅v1，发布于2026-08-17。初始猜测的`/versions/1/files`等端点404已保留，随后通过官方页状态与实际`/public-api/datasets/km8rkfgcpb/files?folder_id=root&version=1`取得3个文件元数据：两本xlsx、一份PDF。没有读取PDF。

按下载前计划与输入锁取得两本xlsx，大小/SHA-256与官方API逐项一致。仅统计OOXML公式元素及表名，结果两本12张表全部0公式；独立openpyxl `data_type == 'f'`库存同样为0，源文件哈希不变。这与描述声称S1的Descriptive_statistics含live formulas不一致。不能由作者说明倒推一个不存在于公开文件的错误公式，更不能把published/corrected两组数值当修复候选/真值，故停止本来源模型实验。没有读取单元格值、公式正文、Known_issues、README或修订标签，没有修改/转换工作簿。

官方文件哈希：S1 `64c469cf01952cb7188e19a88d48a6e44016954ad4ae23f4e03be99262269bf7`，S2 `2e08ab59ddb13aabf157b646d610ef056970079356a5b4530e0395978893aad6`。公开回执为`MENDELEY_KM8_METADATA_20261019.json`、`MENDELEY_KM8_FILES_20261019.json`、`MENDELEY_KM8_INVENTORY_20261019.json`及`MENDELEY_KM8_INVENTORY_VERIFICATION_20261019.json`；原件留在忽略目录。

## 下一步

继续寻找保留实际公式、明确修订沿革且有业务核验依据的来源，优先长期维护的科学/工程工具原件；只叙述错误的论文、数据值更正或公开输出表不能代替底层公式。对许可未知线索保持未准入，不把未解决问题表述成无错误或已合格。新机制要有独立输入证据，不恢复M9/M10及历史已否证规则，不用更多旧案例调参掩盖自然数据缺口。
