# 自然错误来源检索与候选处置登记

登记日期：2026-10-19。范围为公开可追溯的自然静默公式错误来源。论文原模型和所有预测继续冻结；本登记只整理来源级证据，不产生模型准确率数据。

## 检索回执

| 检索批次 | 查询/渠道 | 回执 | 结论 |
|---|---|---|---|
| 历史检索 01 | GitHub commit search：2023年前的 `"formula error" xlsx`、`"fix formula" ods`、`"corrected formula" xls`、`"formula bug" spreadsheet` | 4个查询成功，47个去重命中；逐项检查提交和工作簿路径 | 原始查询使用`committer-date:<2023-01-01`，不是2013年前。仅找到文件格式/导出、改名或无法取得工作簿正文的候选；没有认证自然错误对。原始回执在`source_evidence/HISTORICAL_REVISION_SEARCH_01.json`及`source_evidence/raw/HISTORICAL_REVISION_SEARCH_01/`。 |
| 历史检索 02 | GitHub commit search：`Tuxprogrammer/msu_ece4723`公式修复提交及2023年前`"fix formula" xlsx` | 2个查询成功，21个去重命中；审阅提交差异 | Software Metrics 是开发证据；其他命中属于解析器/格式兼容改动、测试夹具或无修复真值。没有新增最终来源。回执在`source_evidence/HISTORICAL_REVISION_SEARCH_02.json`。 |
| GitHub 检索 03 | 2026-10-18查询`"corrected formula" xlsx`、`"formula error" spreadsheet`、`"fix formula" xlsm` | 查询成功，检查19个提交，其中5个触及工作簿文件 | 5个均未认证自然静默公式错误真值；包括生成文件、删除运行数据、模板修订或提交叙述缺独立业务核验。详见`source_evidence/NATURAL_REVISION_SEARCH.json`。 |
| GitHub 检索 04 | 2026-10-19追加4个提交元数据查询 | 4个查询成功，检查19个提交，0个触及工作簿 | 无新增候选；回执`source_evidence/NATURAL_REVISION_SEARCH_20261019_2.json`。 |
| 学术索引/搜索端点 05 | Google与DuckDuckGo网页搜索；Crossref、OpenAlex题名/关键词检索 | Google和DuckDuckGo各超时20秒；Crossref与OpenAlex各返回20项并保存原始响应哈希 | 结果为ExceLint、Enron语料错误检测等研究论文，没有识别出原/修订工作簿对或公式级真值；新增合格来源为0。回执`source_evidence/NATURAL_REVISION_SEARCH_20261019_3.json`，原始响应在忽略的`source_evidence/raw/source_search_20261019_3/`。 |
| 学术与官方网页检索 | OpenAlex、Crossref、GitLab及官方/作者来源目录 | 既有搜索记录见`NATURAL_REVISION_SEARCH.log`、`NATURAL_SOURCE_COLLECTION.log`和`../followup_20261014/source_discovery/NATURAL_NEW_DOMAIN_REPORT_20261018.md` | 找到来源线索及工具目录，但网页/文件可访问不构成原始错误表、修订对或公式级真值。GitHub匿名API曾限流；当前登记不把未完成请求记为零命中。 |

## 候选来源处置

| 候选 | 已有证据 | 未满足的准入项 | 当前处理 |
|---|---|---|---|
| Reinhart–Rogoff / Herndon–Ash–Pollin | 已取得PERI的2013-05-17复现包；含作者标注的`RR.xls`、HAP R代码及派生`RR-keycolumns.xlsx`。R代码明确将五国排除标作“Spreadsheet error”，PERI更正说明记载Belgium遗漏。 | 缺原始错误版/修订版工作簿配对；`RR-keycolumns.xlsx`是派生输出，不是修订件；公开证据未给出具体错误公式格坐标。R脚本声明BSD-2-Clause，但原始工作簿的单独许可范围未确认。归档原表和Dropbox仍超时。 | 因已检查转换副本中的公式，整个R&R案例永久降为已揭示开发证据；不计来源/家族/错误格，不运行准确率评分。取证细节见`source_evidence/rr_followup/ACQUISITION_AUDIT.md`，原件留在忽略的`private/`目录。 |
| Excel Easy：摊还、预算、资本投资 | 3个教学工作簿链接返回xlsx响应；本轮查看预算、贷款页面及网站入口，没有发现明确再分发许可或历史版本入口。 | 教程模板不等于曾发生过的自然错误；无可信原/修订对、公式错误标签、独立业务核验、明确许可或历史版本；三份也尚未证明模板家族独立。 | 暂不下载或纳入控制集；不算自然错误来源或最终数据。若未来取得明确授权，再评估其教学控制用途。 |
| NSW Treasury：Rapid CBA、Employment Calculator、Outcome Values Database | 官方工具目录及3个工作簿链接已识别。NSW一般版权页声明网站材料采用CC BY 4.0，但排除未明确纳入的第三方材料；三个文件HTTP响应的Last-Modified分别为2026-03-02、2026-10-12和2026-08-11。 | 未找到文件级许可说明、历史版本下载页或原/修订对；Last-Modified只描述当前文件服务元数据，不构成历史版本链；工具之间的模板独立性未验证。 | 保留为干净控制/复杂度候选，但在核实具体工作簿确属许可范围、公式库存及模板家族前不下载、不评分；不能计自然错误来源或模板准入。 |
| StampZ-III | 公开提交包含修订ODS；原/修订公式在Q8:Q105呈一致引用偏移，表头和同表列支持同行关系。 | 原表输入区与公式缓存均为空；未确认许可；只能确认公式级模式，不能证明已产生错误结果或自然业务损害。 | 只保留为开发期公式候选；98格不计可评分错误或新准入来源。详见`STAMPZ_SEMANTIC_AUDIT.md`。 |
| Enron / Info1 | 177本工作簿完成来源级库存；Info1标签与公式格不完全重合；Enron作者事件有部分公式差异。 | 标签不能直接确认正确替代公式；版本中混有非公式改动与转换保真问题，独立公式真值为0。 | 不作为修复准确率数据。详见`ENRON_INFO1_AUDIT_RESULTS.md`。 |

## 2026-10-19 EuSpRIG事故语料论文线索

OpenAlex发现Thorne与Collins的论文*Anatomy of a Spreadsheet Failure, Analysing the EuSpRIG Horror Story Corpus*（arXiv:2609.31815v1，2026-09-25）。通过arXiv Atom API核对官方题名、作者、版本及日期；审阅PDF SHA-256为`e78f338da914a1058a14238750260ed5f03c720186a9030474d79280e3e503f0`。论文称121起去重事故、其中35起Formula & logic，并在附录A列案例级来源链接；论文说明分类有争议且为案例级，许多报道细节有限。PDF和附录超链接中未发现数据集下载URL/DOI/仓库地址/许可声明。

直接检查EuSpRIG公开Horror Stories页面及其REST API页面ID 2510、Original Horror Stories页面ID 2518：可访问的是按事故陈列的新闻叙述，不是论文提及的清理数据文件；未找到CSV/XLSX/逐格标注下载入口。结论仅限本轮公开入口审计，不能推断作者私人数据集不存在。定向复核公式案例POB2302（myocarditis statistics）对应的WhatDoTheyKnow请求页面，当前页未发现可验证的原/修订工作簿对或公式单元格映射；未据此断言FOI记录无附件。相关新闻、官方更正叙述和事故级分类均不足以产生逐格公式真值。

处置：可用作后续来源发现索引；论文数据集可访问性、版本、许可及字段映射未确认。新增合格来源/模板家族为`0/0`，不获取案例工作簿、不运行模型、不评分、不调参。详细链接、证据边界与处置见`EUSPRIG_CORPUS_AUDIT_20261019.md`。

## 研究门槛与后续动作

- 当前至少3个责任主体、4个模板家族只达到开发实验的最低探索准入；不是最终验证集。最终公开来源仍需至少6个历史未用且相互独立的来源、15个去重模板家族，并通过逐来源许可证、版本沿革和逐格真值审计。
- 只要真值不够，不调模型规则，不用`unknown`或不支持样本冒充正确或从覆盖率分母剔除。
- 对可能成为最终来源的候选，在任何预测之前先核实公开许可、原修订时间线、模板家族和可独立确证的标签；若后续标签已被查看或用于选择，整个来源降为开发证据。
- R&R候选现已揭示且降为开发证据；继续寻找未揭示的官方审计勘误、政府更正档案或作者修订对，并先核许可、历史版本和标签证据。对NSW/Excel Easy只核验许可文本、历史版本目录及模板关系；在明确其用途前，不将其升级成自然错误来源。
- 任何新候选若准备留作最终测试，须在获取公式正文前完成预测冻结、纳入规则和来源/模板隔离；本次R&R下载和公式检查均不用于最终评价。

## 2026-10-19 后续元数据筛查

本轮仅检索提交与仓库元数据，未获取工作簿正文、未运行模型、未检查或揭示任何标签，也未改变纳入规则。

| 查询/候选 | 新核查证据 | 处置 |
|---|---|---|
| GitHub commit search：`"spreadsheet error" xlsx corrected` | API报告12条；查看返回前10条。出现一个将以`=`开头的XLSForm文本误写为公式的导出软件缺陷，另有公式计算引擎、Excel兼容/往返等软件提交。同一XLSForm提交在`jnm/kpi`与`kobotoolbox/kpi`重复出现。 | 未发现业务工作簿的原/修订文件对，0个新来源、0个新家族。软件bug提交不作为工作簿自然错误样本。 |
| GitHub commit search：`"fix formula" xlsx` | API报告932条；查看返回前10条。所见为公式检测/导入/导出、解析和公式注入防护等代码改动。该查询结果量大且前10条偏软件工程，不能据此声称已审完整个命中集。 | 无可认证的新自然错误来源；停止将宽泛命中数用作来源进展指标。 |
| `micro-solution/BPA` | 2026-10-19重新读取GitHub仓库API元数据：仓库公开、非fork，但`license`字段为`null`。原/修订blob不同及修订提交文字仅证明候选沿革，不能证明公式标签。 | 暂不获取工作簿正文；因没有明确许可，留在保留候选，不计入来源或模板。若不能取得明确授权/适用许可，关闭候选。 |
| `drjlevi6/Data-Scientist` | 2026-10-19重新读取GitHub仓库API元数据：仓库公开、非fork，但`license`字段为`null`。文件大小明显变化，修订提交同时修改notebook，尚无工作簿级差异证据。 | 暂不获取工作簿正文；许可和修订范围均未过关，保留为候选，不计来源或模板。 |
| `mike442144/gsupdater` | 新查到的提交说明实际报告CIQ数据导出格式变化引发的解析/映射代码缺陷，包括缺失字段指向表头行、百分比缩放及列选择问题；不是作者修订某业务工作簿的公式。仓库API的SPDX许可字段为`null`。 | 归类为软件侧数据摄取错误，不属于自然公式错误工作簿来源；不获取或纳入候选工作簿。 |

本轮后合格最终公开来源/模板家族仍为`0/0`。提交搜索的页面结果只作为线索筛查，不替代源文件、版本沿革、许可、模板去重及逐格独立真值审核。下一步优先转向有正式版本存档与明确开放许可的政府审计勘误/更正档案；在找到具体修订工作簿前继续冻结原模型和所有评分。

## 2026-10-19 DOE/OSTI 替代端点复查

本轮只复核元数据与公开目录可达性，未下载报告全文或工作簿，未查看公式内容，未运行模型或改变准入规则。Crossref DOI API（HTTP 200）和OpenAlex DOI记录（HTTP 200）再次确认题名`Strontium-90 Error Discovered in Subcontract Laboratory Spreadsheet`、1999-07-31发布日期，以及DOI资源指向OSTI PURL；OpenAlex标为开放获取，但`license`与`license_id`均为null，记录没有列出工作簿附件或修订文件。原始JSON响应已保存于忽略目录`source_evidence/raw/NATURAL_SOURCE_RETRY_20261019/`，SHA-256分别为Crossref `7aef963b23ae5a5cd1005b7bc494511f9d7d19c8827d2496408cbdca201904eb`、OpenAlex `21af77b9fce7c4c0f1c6a9867b7e54daac012b159e18d6b24f44ba6242ec1bcc`。

对`www.osti.gov/api/v1/records?doi=10.2172%2F12185`、OSTI PURL `https://www.osti.gov/servlets/purl/12185-3MGwCS/webviewable/`、UNT检索页及Internet Archive CDX的重试分别超时（约20-25秒）；`api.osti.gov`替代主机无法解析。Crossref/OpenAlex只能支持报告书目及错误事件线索，不能证明工作簿附件、许可、原修订链或逐格公式真值。因此该候选继续标为“真实错误事件、工作簿级证据未取得”，不计自然来源或模板家族，也不启动预测；访问失败不解释为零命中。

补充检索边界：2026-10-19尝试以Google和DuckDuckGo搜索官方审计/政府工作簿更正线索，连接均超时；Bing请求虽返回搜索页，但本次抽取未取得可核查的结果条目。该检索受阻，不解释为“没有来源”，也不改变`0/0`准入计数。

## DOE/OSTI 候选线索

Crossref/OpenAlex 元数据检索命中 DOE/OSTI 题录 [Strontium-90 Error Discovered in Subcontract Laboratory Spreadsheet](https://doi.org/10.2172/12185)，报告日期为1999-07-31，机构元数据列出 West Valley Demonstration Project 与 US Department of Energy。该题名显示存在真实报告线索，但这不是工作簿级标签，也未读取报告正文。

Semantic Scholar 的独立 DOI 记录提供摘要，称项目健康物理学家与环境科学家发现了承包商用于 Sr-90 分析数据处理的电子表格中“一系列错误”。它确认存在自然错误事件，但不指出公式、单元格或修订版本。

当前证据边界：Crossref资源字段指向 OSTI PURL；OpenAlex列出 OSTI 与 UNT 两个仓储位置，但许可均为未知；Semantic Scholar也未列出许可，并明确提示应回源核对版权。对 OSTI 书目页、API/PURL和UNT馆藏页的请求均超时；OpenAlex全文内容端点返回401。尚未证实报告是否附带原始/修订工作簿、具体公式单元格、修订链或明确再分发许可。因此只保留为未揭示的来源级候选，不计来源/家族，不获取或预测任何工作簿，不运行模型。下一步先通过可访问的机构目录/出版者记录核实附件、许可与版本元数据；只有这些门槛成立，才制定预登记并考虑取得原始工作簿。

## 2026-10-19 仓储元数据与 Zenodo 候选配对审计

API元数据回执及响应SHA-256见`source_evidence/ZENODO_METADATA_SCREEN_20261019.json`；原始响应保存在忽略的`source_evidence/raw/`。本批未改变纳入规则，也未新增最终来源或模板家族。

| 候选 | 元数据及版本对审计 | 处置 |
|---|---|---|
| Zenodo 4091366 | CC BY 4.0；记录称v1.1修复了small errors and formulas，列有`Argentina_Camarones.xlsx`及`Argentina_Camarones_v1.1.xlsx`。预测在版本比较前已锁。两版有57/66个公式；共享位置只有`Global Mean Sea Level!L2`和`M2`两个公式改写，均是将原聚合表达式改为引用新增的同等统计单元格，缓存值一致。另有9个公式增加、12个非公式值变化，工作簿还新增South Africa站点。没有逐格勘误或独立业务证据认证原有错误。 | 不合格自然错误来源；0个可评分错误格、0个新增家族。详见`research/zenodo_4091366_dev1/PAIR_AUDIT.md`。公开工作簿保留在本地忽略目录，不上传。 |
| Zenodo 6594745 | CC BY 4.0；2017/2022参数表同记录，说明仅称参数清单“可能有遗漏或错误”，没有公式纠正声明或公式级修订真值。 | 不作为公式错误来源；可能的干净/复杂度对照仍需先定义使用目的。 |
| Zenodo 12586563 | CC BY 4.0；单本教学用toy spreadsheet，描述称供学习者寻找错误和重组数据。 | 教学错误示例，不是自然发生错误及修订对。 |
| Zenodo 14512695 | CC BY 4.0；一个含`Revision01`字样的工作簿，没有查到原版配对或勘误声明。 | 不合格来源。 |
| Harvard Dataverse OQRP6B | CC0 1.0；单一Benninga/Caterpillar财务模型，标题和说明称没有公式错误或缺失数据。 | 只作为干净控制候选，不作错误来源或自然错误来源计数。 |

本轮公开仓储候选仍为自然错误来源`0`、模板家族`0`。Zenodo 4091366是元数据中明确声称修正公式的来源，但正文比对没有定位到经独立证实的错误公式，因此不能因“公式发生变化”升级为可评分样本。下一步继续验证DOE/OSTI的许可与附件，并针对正式勘误、历史版本保存完好的公开研究数据检索；不为增加样本数而把教学错误或版本改写计作自然错误。

## 2026-10-19 faultsfw 注入错误基准审计

重新读取Zenodo 581672官方API记录，确认题名`faultsfw`、开放获取、CC BY 4.0、发布日2015-03-11。描述称33个表格家族（12个人工创建、21个真实工作簿），故障副本由随机选取公式并执行变异生成，含单/双/三故障版本。归档列出的大小2337027字节、MD5 `35f2d4a4d1536eb8c7825a982f2f75b3`；下载归档SHA-256 `47d6950a9275e68b4b3c51177893b2a9dbc3053243e30b7eb88c32bbc6829aec`，ZIP完整性检查通过。归档中有225个`.xlsx`与27个`.xls`故障版本；README已公开指出至少一个配置项对应非公式故障，因此这是标签公开的注入错误外部基准，不是盲测，也不计自然来源/模板家族门槛。按`FAULTSFW_PREREGISTRATION.md`固定全量`.xlsx`输入后运行冻结模型；`.xls`保留在支持边界统计，不能当正确预测或从端到端支持说明中删去。配置文件在预测锁前尚未用于评分。

## DOE/OSTI 访问回执更新

2026-10-19重试官方API `https://www.osti.gov/api/v1/records/12185`和书目页 `https://www.osti.gov/biblio/12185`，两者均在25秒后连接超时。该候选仍是来源级真实错误事件线索，但附件、许可证、工作簿版本和公式格真值未核实；处置仍为访问受阻且不计来源/家族，不把超时记录为零命中。

## faultsfw 预测与评分结果

按预登记先锁定225个`.xlsx`故障变体及逐文件哈希，再读取配置和注入前原始模板。冻结论文模型完成225/225项推理；1进程与8进程预测哈希逐文件一致。219项有可映射的配置和原模板，确认374个公式故障格；6项因缺配置/原模板而标记格级真值未知，其建议仍进入全部建议精确率分母。论文模型全文本精确恢复149格，正确修复覆盖率`149/374=39.84%`；全部建议`149/2,116=7.04%`精确。另27个`.xls`版本未送入`.xlsx`入口，保留为格式支持限制。已计分模板家族31个，属于该公开注入基准内部家族，不计自然来源或最终验证门槛。各错误类型、并行资源、范围限制及逐输入锁见`FAULTSFW_RESULTS_20261019.md`和`source_evidence/FAULTSFW_INPUT_LOCK_20261019.json`。该结果显示该注入机制上的误报和覆盖不足；不得针对同一公开基准调参后重新宣称独立验证，也不支持自然错误精度或90%结论。

## AEDIST Err:510 natural development replication

2026-10-19取得`MinhHaDuong/aedist-technical-report`同一ODS工作簿的缺陷版与同日修订版。仓库许可元数据为CC-BY-4.0；Git历史和`data/reference/PROVENANCE.md`明确披露`Power plants!N254:N255`的Err:510修复，因此该案例在任何模型预测前已属于揭示案例，永久排除最终盲测。原版和修订版通过LibreOffice转换后，目标公式分别保持为原版畸形嵌套公式及修订公式`=1330/2`、`=N254`。

按预登记对两个版本分别运行冻结论文模型和dev11，不调参。论文模型把两个单元均排入局部异常，但分别建议邻格的错误公式；两格精确修复均失败（0/2）。dev11对两格均弃权，精确修复也为0/2。两输入在1与8 worker下的预测输出SHA-256逐一一致，所有源文件哈希校验保持不变。两项任务使请求8 worker批次实际至多两项并行，墙钟7.34秒、子进程CPU合计14.49秒、采样峰值RSS约283.3 MiB，相对单worker约1.90倍加速；这不证明八路饱和。全部原始文件、输出和运行日志留在忽略的`source_evidence/raw/aedist_err510/`。逐格结果与局限见`research/aedist_err510/RESULTS.md`及预登记。

该案例仅新增一个已揭示自然开发来源线索，不计最终验证来源或模板家族；最终验证计数仍为`0/0`。不能计算全工作簿建议精确率，不用于调参。

## 2026-10-19 benchmark/source lead screening

GitHub repository search returned `plasma-umass/DataDebug` (https://github.com/plasma-umass/DataDebug), an Excel data-debugging system. Its README describes ranking cells for human review, and the repository is GPL-2.0. The tree contains one `CheckCellTests/TestData/grades_spreadsheet.xlsx` plus `ErrorGenerator` and simulation tests, but no author-corrected workbook pair or independently documented natural error labels. It is a methods/code lead, not a natural-error dataset; no model was run.

The same search surfaced `RUCKBReasoning/SpreadsheetBench-2` (https://github.com/RUCKBReasoning/SpreadsheetBench-2). Its README lists a `Debugging` category with input and golden-response workbooks hosted on Hugging Face, but GitHub repository metadata has no license, the repository tree does not include the dataset files, and the Hugging Face dataset API timed out during this screen. The task benchmark description alone does not establish naturally occurring silent formula errors, source-authored correction lineage, or independent cell-level truth. Defer pending accessible dataset terms and provenance audit; do not infer that the dataset has zero eligible cases from the timeout.

These two screens add no qualified natural source or template family. They do not change the final-validation count (`0/0`) or justify model tuning.

## 2026-10-19 London Whale 官方报告目录复查

本轮跟进GitHub文章提交中关于JPMorgan London Whale公式错误的线索，仅核查报告书目/官方目录，不读取工作簿或错误标签、不运行模型。Bing精确查询`"JPMorgan Chase Whale Trades" "S. Prt."`可返回搜索页，但前列结果与目标报告无关，未获得可靠报告编号；Google连接超时。Congress.gov搜索请求返回Cloudflare 403。GovInfo `committee-publications`集合页返回HTTP 200，但页面内容是集合介绍而非目标报告条目。对猜测的包路径`CPRT-112SPRT76071`及`CPRT-113SPRT81946`请求均返回HTTP 200、约44 KB HTML错误页（并非PDF）；`file`检查确认响应不是PDF，因此这些路径不能用来确认报告编号或附件。上述端点和响应只说明访问/路径状态，不构成报告不存在的证据。

此前线索文章称其引用2013年美国参议院常设调查小组委员会报告，描述某替换模型公式把两个值相加而未取平均；但当前未取得正式报告书目、附件清单、原始/修订工作簿、明确再分发许可或逐格独立真值。该候选继续停留在来源级线索，不获取可疑工作簿、不计来源或模板家族、不作准确率评分。检索回执：Bing `https://www.bing.com/search?q=%22JPMorgan+Chase+Whale+Trades%22+%22S.+Prt.%22`；GovInfo集合 `https://www.govinfo.gov/collection/committee-publications`；Congress.gov搜索端点被拦截。后续若重试，先从GovInfo官方API/目录按标题与委员会元数据定位唯一包ID，再核对报告正文的引用与附件索引；只有发现允许公开使用且可证实版本链的工作簿对，才继续准入审查。

## 2026-10-19 GitHub 公式错误提交元数据筛查

使用GitHub commit search API查询`"spreadsheet error" formula extension:xlsx`、`"corrected formula" spreadsheet extension:xlsx`、`"incorrect formula" spreadsheet`、`"formula errors" workbook`及`"spreadsheet mistake" formula`。前两项各返回0条；后三项分别返回10、594和4条。宽泛结果中近期软件工程和生成型仓库噪声较多；仅从`"formula errors" workbook`返回结果中检查前20项提交元数据并核查3个可能包含真实工作簿的仓库/提交，不把搜索命中总数视作已审样本。

| 候选 | 提交级核查 | 处置 |
|---|---|---|
| `nathaliejoyfutolan-ai/act-da-tracker-updater`，`360ac92b8a` | 提交标题为“Report exact workbook formula errors”，但差异只有`src/update.mjs`的7行新增、3行删除；仓库创建于2026-10-17，GitHub许可字段为空。 | 软件/报告代码，不含工作簿修订对或公式真值；排除，不下载其他文件。 |
| `krwizxp/fcupdater`，`15df74736d` | 提交标题称更新Chungcheong燃油工作簿，差异API列出`.xlsx`路径但文件增删统计均为0；仓库许可字段为空。 | 目前只有定期数据刷新元数据，没有公式错误修订证据及可核许可；不取工作簿正文，不计来源。 |
| `sabodaha/windpark-rechner`，`73e15a649c` | 提交涉及风电计算器方法说明页面，未修改工作簿；仓库许可字段为空。 | 方法文档不是错误修订对；排除。 |

本轮无可准入自然错误来源或新模板家族。GitHub提交搜索只用于发现候选，工作簿文件被提及或更新不等于公式错误被更正；最终验证仍为`0/0`，模型和规则保持冻结。

## 2026-10-19 DataCite 与 ONS 来源/控制筛查

本轮继续查找带明确许可、可追溯版本和公式级真值的公开来源。没有读取潜在盲测候选的公式或标签，也没有运行模型。

| 候选/检索 | 核查证据 | 处置 |
|---|---|---|
| DataCite 目录检索 | API全文查询`spreadsheet formula error`返回98条，`spreadsheet error correction`返回152条；这些是全文索引命中数，不是已逐项审阅的来源数。补做题名字段检索后，题名同时含`spreadsheet`与`formula`的16条主要是公式研究、代码或理解度数据集；题名同时含`spreadsheet`与`correction`的3条中，Zenodo 1014025/1014026标题为`Correction occurrence analysis spreadsheet`。 | 宽泛命中不作为来源进展指标；逐一检查显著候选的描述、版本关系和许可后再决定是否获取文件。 |
| Zenodo 1014025/1014026 | DataCite记录把两条DOI列为同一数据集的版本关系，许可为CC BY-NC 4.0。摘要明确说明该Excel记录京剧演唱训练中的教师反馈、信号分析方法及分类维度；1014026文件清单列出`Correction_occurrence_spreadsheet.xlsx`（94,217字节）。 | `correction occurrence`指教学反馈事件，不是工作簿公式纠错；不下载、不计自然错误来源或模板家族。 |
| ONS GERD年度修订表 | 官方页说明内容是“首次发布值与五年后的值”，提供当前`.xls`及previous versions入口，页面标注Open Government Licence v3.0。独立BIFF审计确认当前版与历史版各有32个公式；转换地址完整，但每本有7处缓存非完全相等及6处公式反编译写法差异。 | 修订表不是公式勘误，不能计自然错误来源。原始缓存/Calc重算差异及反编译写法未解决，预登记停止条件触发；结论`inconclusive`，不进入模型控制实验。当前和历史版属同一业务表模板，不另计模板家族。 |
| ONS BERD年度修订表 | 官方页同样描述首次发布值与五年后的值，提供当前`.xls`，页面标注Open Government Licence v3.0。独立BIFF审计确认34个公式；地址完整，但有7处缓存非完全相等及8处公式反编译写法差异。 | 该表不能计自然错误来源。与GERD相同，转换保真结论`inconclusive`，不进入模型控制实验；与GERD共同只构成近似控制模板候选，不计错误来源或独立错误家族。 |
| ONS产品分类更正数据 | 官方更正页提供`.xlsx`、标注Open Government Licence v3.0；说明问题源自少数产品历史人工分类不一致，属于统计数据分类修正。 | 明确排除公式错误评分；只作为“非公式错误更正”边界案例记录，不作为公式真值。 |

官方页面：GERD https://www.ons.gov.uk/economy/governmentpublicsectorandtaxes/researchanddevelopmentexpenditure/datasets/revisionsspreadsheetforannualdatagerd ；BERD https://www.ons.gov.uk/economy/governmentpublicsectorandtaxes/researchanddevelopmentexpenditure/datasets/revisionsspreadsheetforannualdataberd ；产品分类更正 https://www.ons.gov.uk/economy/inflationandpriceindices/adhocs/3621datasetaccompanyingtheproductclassificationerrorcorrectionfebruarytojuly2026 。DataCite查询使用`https://api.datacite.org/dois`的全文及题名字段查询；Zenodo候选DOI为`10.5281/zenodo.1014025`和`10.5281/zenodo.1014026`。

本轮新增合格自然错误来源和最终模板家族均为0，最终验证仍为`0/0`。ONS表仅为未通过格式保真门槛的控制候选；已按预登记完成`.xls`转`.xlsx`审计，因21处缓存差异和20处反编译写法差异判为`inconclusive`，不运行控制实验，也不基于它们调整原模型或规则。宽泛DataCite命中数不得表述成穷尽搜索。

## 2026-10-19 官方目录定向复查

本轮继续优先寻找官方审计/勘误、政府更正档案或作者修订对；不下载未通过来源/授权审查的工作簿，不运行模型。

| 渠道 | 本轮请求与结果 | 结论和边界 |
|---|---|---|
| DataCite | 初始探索用了非标准`title:`字段，其零计数已撤回；正式以`titles.title:`查询。`spreadsheet AND erratum`、`spreadsheet AND revision AND formula`返回0；`spreadsheet AND correction`返回3项，分别为一篇终端用户纠错行为研究及此前排除的京剧数据两版本。全文`spreadsheet formula error`首批40条题名以无关数据集、教程和代码为主；`spreadsheet erratum`的11项题名未形成修订对。 | 规范字段回执见`source_evidence/OFFICIAL_CATALOG_SCREEN_20261019.json`；仅完成限定结果集筛查，不代表穷尽。纠错行为研究不提供本轮可认证修订对。 |
| Crossref | `spreadsheet error correction`、`spreadsheet errors government audit`、`formula error workbook corrected spreadsheet`三次请求均返回HTTP 429。 | 限流，不能记为零命中；本轮不重试。 |
| Bing | 5条英文精确短语查询均HTTP 200，但结果页仍主要返回本地化词典、通用Office产品及无关网页。 | 搜索结果不具备可核来源价值，排除本轮判断；不是无来源证据。 |
| GOV.UK Search API | 精确短语`"spreadsheet error"`返回0，`"formula error"`返回10条，`"spreadsheet correction"`返回8条，`"spreadsheet mistake"`返回0。进一步检查8个发布页及8个HTML正文，找到MOD关于2018年VCC年龄比例的明确公式错误修订说明。 | 初始只查标题不足以排除正文勘误，已补查正文并取得一条真实事件线索；来源资格仍待公式库存与原修订链审计，见下节。索引不代表完整官方档案。 |
| Hugging Face / GovInfo / HSGAC | SpreadsheetBench-2数据集元数据请求超时；GovInfo试探的旧式`wssearch`路径返回404；Senate HSGAC WordPress搜索接口返回403。 | 访问受阻或端点不适用，均不解释为数据不存在；SpreadsheetBench-2维持未审候选，不下载。 |
| ONS GERD / BERD | 已按预登记下载三个官方`.xls`并完成独立BIFF库存及两轮转换比较；98个公式地址全部保留，但原始缓存与Calc结果有21处非完全一致，公式写法另有20处差异。 | 结果inconclusive，触发控制停机条件，不运行模型；见`ONS_CONTROL_CONVERSION_RESULTS.md`。不计自然错误来源/模板家族。 |

正式目录回执及原始响应哈希见`source_evidence/OFFICIAL_CATALOG_SCREEN_20261019.json`；发布页与正文分别见`source_evidence/GOVUK_CANDIDATE_FOLLOWUP_20261019.json`、`source_evidence/GOVUK_CHILD_SCREEN_20261019.json`。只有目录和元数据请求使用8个网络线程，这不是模型8进程吞吐实验。初始探索请求未全部落盘，不将其声称为完整可重放搜索。

## 2026-10-19 MOD cadet statistics 官方勘误线索

官方[2021年统计正文](https://www.gov.uk/government/statistics/mod-sponsored-cadet-forces-statistics-2021/mod-sponsored-cadet-forces-1-april-2021)明确记载：2018年4月1日VCC的Table 2因公式错误修订年龄比例，实际人数不变。本轮在查正文时已看到该说明，因此是已披露来源线索；没有声称盲测资格。按`MOD_CADETS_SOURCE_PREREGISTRATION.md`和后续元数据限定补充，先核[2018年原发布页](https://www.gov.uk/government/statistics/mod-sponsored-cadet-forces-statistics-2018)的OGL v3声明及附件，再取得附件、记录哈希，仅统计公式元素并映射工作表名，未阅读公式正文或数值。

2018年附件HTTP 200，958,874字节，SHA-256为`22a05449aee79b4143ece5c7b7911dc1ae3ebc82ac523c18326f65f253cb16ff`，服务器Last-Modified为2018-05-25（该时间不单独证明未经修订）。9张表共82个公式元素，全部位于隐藏的`Graphs16dnu`；`Table 2`及其余公开统计表均无公式。工作簿另有三个external-link XML文件，未解析其内容、未访问链接。公开Table 2不提供底层错误公式，不能用变动后的比例代替原公式真值；停止本候选模型实验，不再为评分获取修订表。该真实错误事件保留为底层源文件未公开的线索，不计自然错误来源/最终家族。

取得回执、表级库存、工作表映射见`source_evidence/MOD_CADETS_ACQUISITION_20261019.json`、`source_evidence/MOD_CADETS_INVENTORY_20261019.json`和`source_evidence/MOD_CADETS_SHEET_MAP_20261019.json`；原文件留在忽略目录。最终验证仍为`0/0`。ONS控制审计也因未解决保真差异停止。下一步继续寻找能取得底层原始/修订公式的官方公开源文件，不能以报道、输出统计表或搜索命中替代。

## 2026-10-19 SpreadsheetBench-v2 数据集可达性与任务类型复核

通过GitHub官方API读取`RUCKBReasoning/SpreadsheetBench-2`仓库元数据、README和递归文件树。仓库为公开、非fork，默认分支`main`，仓库根`license`字段为`null`；数据README把数据集链接至Hugging Face `KAKA22/SpreadsheetBench-v2`，并说明数据文件不在该Git仓库树内。README将`Debugging`描述为“Formula debugging and error correction”，每个任务有`spreadsheet_path`和`golden_response_path`；它没有说明这些公式错误是否自然发生、golden文件是否为原作者/组织的修订件、标签如何独立核验，也没有给出逐格自然错误真值规范。README要求实验前重算输入及golden工作簿，故未来准入还需审计重算对原始公式/缓存/标签的影响。

本轮用IPv4重试Hugging Face官方数据集API、数据集文件树和原始GitHub README端点：Hugging Face连接阶段超时（HTTP 000），raw.githubusercontent.com在25秒内无响应；GitHub官方API成功提供仓库README与文件树。未下载工作簿、未读取公式/标签、未运行模型。证据入口：仓库元数据 https://api.github.com/repos/RUCKBReasoning/SpreadsheetBench-2 ，README https://github.com/RUCKBReasoning/SpreadsheetBench-2/blob/main/README.md ，仓库树 https://api.github.com/repos/RUCKBReasoning/SpreadsheetBench-2/git/trees/main?recursive=1 ，数据集 https://huggingface.co/datasets/KAKA22/SpreadsheetBench-v2 。

处置：本项目不是自然错误来源候选，而是可能属于公开注入错误评测的候选；仍不计来源或模板家族、不运行模型、不把超时解释成零个合格样本。许可方面，论文中的数据集许可声明比GitHub根仓库元数据更具体，但仍需取得数据集自身的`README`/许可文件与版本记录，并核对其是否与论文声明一致。

### 论文全文复核：重新分类为注入错误候选

从arXiv官方API和PDF取得论文*SpreadsheetBench 2: Evaluating Agents on End-to-End Business Spreadsheet Workflows*（arXiv:2606.29955v1，2026-06-29）。PDF SHA-256：`4c72f1fc306242cab478e10dca03e41cd8d55730b1db85b9c895899ae04eeaa6`。摘要称基于真实商业数据、专家标注并验证，共321项任务；B.1列出BSE India、Bloomberg、Screener.in及NYU Stern/Damodaran来源。论文A.2说明为控制版权，不再分发原始来源文档，发布的是专家构造的派生任务，必要时修改数值和结构；A.4声明数据集采用CC BY-SA 4.0，评估代码采用MIT。论文所述许可是重要证据，但尚未取得Hugging Face数据卡/许可文件作版本一致性核验。

论文第2.1节与B.4进一步明确：Debugging共100项任务；任务说明不告知错误类型或位置；十类错误经真实金融建模/会计实践中的错误迭代归纳，每个Debugging任务含一个或多个`injected errors`，要求修复至预期状态。专家在构造阶段投入约500小时，选取任务还经过双专家独立解决/一致性检查。故这100项不是自然发生错误样本，不能充当自然错误来源，但可能构成公开工作簿注入错误类别中的独立基准。该基准覆盖双重计数、硬编码、公式错误、错误平均范围、跨表引用、符号、相对/绝对引用、单位等多类业务/公式机制；它是端到端任务集，不能把全部单元格修改都当成公式错误。

本次只审阅官方论文文本及先前已审的GitHub README/树，未取回Hugging Face数据卡、文件清单、输入表或golden文件，未检查任何公式/标签，未运行模型。实验前仍须确认数据文件许可/版本、Debugging子集完整清单、输入与golden差异、每类目标错误及干净格、错误是否仅由作者注入、golden公式是否可作为正确修复真值、自由文本指令中未标目标/错误类型是否会造成额外信息不足，并审计README要求重算工作簿造成的公式/缓存变化。通过这些门槛前不列入可评分注入基准；通过后需冻结本模型和评分器，预登记后再运行。

官方证据入口：论文记录 https://arxiv.org/abs/2606.29955v1 ，PDF https://arxiv.org/pdf/2606.29955v1 ，数据页 https://huggingface.co/datasets/KAKA22/SpreadsheetBench-v2 ，项目代码 https://github.com/RUCKBReasoning/SpreadsheetBench-2 。本轮arXiv API/PDF及GitHub API可访问；Hugging Face API/文件树和`raw.githubusercontent.com`超时。自然错误来源/模板家族仍为`0/0`；本候选暂不计入注入错误实验数据。

### 本地取得与归类更新（2026-10-19）

通过`hf-mirror.com`镜像revision `5a2215ed4121945ab09d8723df2995602090b042`取得`spreadsheetbench-v2-09-10.zip`。再次读取镜像递归文件树，确认LFS SHA-256及本地归档SHA-256同为`52699c974c30aced7125f3d12cdaabbbcbba8db804373d7397a5d3bdf68e5b3e`，大小134,232,213字节。归档ZIP完整性检查通过，清单含`Debugging`目录下100个`*_input.xlsx`和10个`*_golden.xlsx`，覆盖10个任务目录。仅据文件名和目录确认清单，未解析`dataset.json`、工作簿公式或golden内容。

数据卡front matter标注MIT，而论文A.4声明数据集CC BY-SA 4.0；本地未取得独立LICENSE文件。保留两项证据及冲突，按更严格的CC BY-SA 4.0边界仅作本地研究，不推送归档、工作簿、逐格标签或衍生数据。该数据仍只归类为公开专家注入错误基准，绝不计入自然错误来源或自然模板家族数。冻结模型预测由预登记流程执行；输入/黄金哈希锁和预测锁位于被忽略的本地`source_evidence/raw/spreadsheetbench2/`目录，逐任务结果锁定前不读任务JSON或golden工作簿。
