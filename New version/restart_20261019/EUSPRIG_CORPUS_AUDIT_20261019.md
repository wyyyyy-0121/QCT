# EuSpRIG Horror Story Corpus 论文线索审计

检索日期：2026-10-19。用途：来源发现，不是数据集纳入或模型评测。原论文模型保持冻结；本轮未下载事故工作簿、未读取新公式或标签、未运行模型。

## 可复核入口

- 论文：Simon Thorne、Angela Collins，*Anatomy of a Spreadsheet Failure, Analysing the EuSpRIG Horror Story Corpus*，arXiv:2609.31815v1，2026-09-25。官方记录：https://arxiv.org/abs/2609.31815v1；PDF：https://arxiv.org/pdf/2609.31815v1。
- 已审阅PDF SHA-256：`e78f338da914a1058a14238750260ed5f03c720186a9030474d79280e3e503f0`。本地审阅副本位于`/tmp/hg_eusprig_2609.31815.pdf`，未纳入仓库。
- EuSpRIG当前Horror Stories页面：https://eusprig.org/research-info/horror-stories/。WordPress REST API页面ID 2510确认该页面公开列出新闻故事、来源、日期、风险和叙述；未显示论文所称清理语料的文件下载项。
- EuSpRIG旧Original Horror Stories页面：https://eusprig.org/research-info/original-horror-stories/。是按时间倒序展示的事故叙述页面，不是逐格标注数据文件。

## 论文内容与数据集核查

论文称去重整理后有121起1995-2026年事故，其中35起被分入Formula & logic (FL)，并在Appendix A提供事故编号、类别和主要报道链接。论文明确指出许多报道细节有限，因此分类是案例级而非单元格级；“released dataset”被提及为承载案例编码的材料，但论文中未找到下载URL、DOI、仓库地址或许可声明。PDF中的链接检查显示附录链接指向事故报道，而非语料文件。arXiv HTML端点本轮无可用HTML内容；arXiv Atom官方API返回单一v1记录及论文摘要、作者、发布日期。

截至检索时点，在EuSpRIG公开故事目录和论文PDF中未定位到可下载的清理数据集。EuSpRIG页面存在不等于论文数据集已公开；无法确认该数据集可访问、版本、许可、字段完整性或来源映射。此结论限定为本次审阅的公开入口，不推断作者私人材料不存在。

## 事故案例筛查

附录A的FL案例包括Fidelity (NS13)、Fannie Mae (NS09)、University of Toledo (NS08)、Nevada City (NS03)、Reinhart–Rogoff (POB1302)、Snyder County (POB1506)、M&S (POB1604)、Conviviality (POB1801)、Canopy Growth (POB1901)、myocarditis statistics (POB2302)、Putney与Richmond选举 (ACST2410/2412)、Arizona预算 (ACST2504)、Gallatin County (ACST2509)、Thurgau (ACST2502)、Aquarion (ACST2605)等。列表只是事故线索，附录本身没有原始工作簿、修订工作簿、单元格坐标或公式级真值。

重点查看了论文对POB2302的引链：https://www.whatdotheyknow.com/request/myocarditis_and_pericarditis。EuSpRIG当前故事页仍将来源指向AAP FactCheck/FOI线索，并描述数据简化进数据透视表时把应为计数的值求和。本轮对WhatDoTheyKnow请求页的定向网页检查没有发现可下载的原版/修订版工作簿附件或逐格公式映射；这不足以说明FOI记录整体没有附件，仅说明当前可审页面未提供可验证工作簿对。

不将相关新闻、官方更正叙述、公开统计值或事故数量转为公式标签。由于未取得相同工作簿的错误版与修订版、明确许可及独立公式级业务真值，新增合格自然错误来源`0`，新增模板家族`0`。POB2302仍是来源线索，不进入模型或评分。

## 处置

论文可作为未来检索索引，尤其可帮助定位官方审计、更正声明和事故来源；当前不构成自然错误评测集。若未来作者发布清理数据集，应先核查下载地址、版本/时间、许可、事故到原始材料的映射及单元格标签定义。即便事故数据集可用，也须逐案取得可复核工作簿和独立真值后才能计入修复评测。

本轮结果：最终来源/模板家族仍为`0/0`；模型、规则、参数和已锁预测均未改变；未提交任何模型或数据样本。
