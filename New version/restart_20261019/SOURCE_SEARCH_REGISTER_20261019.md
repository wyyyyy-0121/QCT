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
