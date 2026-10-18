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
| Excel Easy：摊还、预算、资本投资 | 3个教学工作簿链接返回xlsx响应。 | 教程模板不等于曾发生过的自然错误；无可信原/修订对、公式错误标签、独立业务核验和明确的再分发许可；三份也尚未证明模板家族独立。 | 仅作干净模板/控制的候选，不算自然错误来源或最终数据。 |
| NSW Treasury：Rapid CBA、Employment Calculator、Outcome Values Database | 官方工具目录及3个工作簿链接已识别；可用于建立真实业务工作簿候选。 | 当前发布文件没有已核实的错误修订史；无历史原/修订对、逐格真值和确认可公开再分发的许可；工具之间的模板独立性未验证。 | 可在许可核验后用作干净控制或工作簿复杂度样本；不能给错误标签，不能计来源/模板准入。 |
| StampZ-III | 公开提交包含修订ODS；原/修订公式在Q8:Q105呈一致引用偏移，表头和同表列支持同行关系。 | 原表输入区与公式缓存均为空；未确认许可；只能确认公式级模式，不能证明已产生错误结果或自然业务损害。 | 只保留为开发期公式候选；98格不计可评分错误或新准入来源。详见`STAMPZ_SEMANTIC_AUDIT.md`。 |
| Enron / Info1 | 177本工作簿完成来源级库存；Info1标签与公式格不完全重合；Enron作者事件有部分公式差异。 | 标签不能直接确认正确替代公式；版本中混有非公式改动与转换保真问题，独立公式真值为0。 | 不作为修复准确率数据。详见`ENRON_INFO1_AUDIT_RESULTS.md`。 |

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
