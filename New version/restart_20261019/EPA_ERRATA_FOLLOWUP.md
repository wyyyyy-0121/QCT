# EPA公开勘误追索记录

## 从官方勘误确认的线索

以下信息来自`source_evidence/EPA_ERRATA_RECEIPT.json`中已记录URL和SHA-256的EPA PDF；本轮通过`pdftotext -layout`再次读取原始PDF内容。

| 来源 | 勘误PDF提供的信息 | 研究判断 |
|---|---|---|
| Carbon Adsorber | 文件名`epa_carbon_adsorber_calc_sheet_7thedition.xlsm`。B12/D12单位描述从“at atmospheric pressure and 77 F”修订为acfm，以匹配手册定义。 | 当前证据是单位标签更正，不是公式修复，不能作为本研究的公式错误样本。 |
| Flares | 文件名`flares_calc_sheet_September 2022.xlsm`。Design Parameters的B39:B43公式更正，以确保体积蒸汽流率不低于最小值；另更新利率及CEPCI默认值。 | 有公式修复线索，但同一修订还含输入默认值更新；需原/修订文件及逐格审计，不能从勘误叙述直接计分。 |
| Incinerators/Oxidizers | Data Inputs的X9:X18从估计控制后剩余排放改为估计减排量；Design Parameters的D36修正稀释因子参与体积流量计算。 | 勘误明确描述了公式逻辑变化，适合作为追索优先项；当前仍没有工作簿版本对和完整业务输入。 |

## 获取尝试与边界

- 按Carbon文件名猜测的EPA URL返回403。这个状态不能证明文件不存在，也没有取得文件内容或哈希。
- 按Flares文件名猜测的EPA URL返回404。由于尚未从官方页面确认准确链接，此结果不能用来断言文件已下架。
- Internet Archive CDX查询未在20秒内返回；Common Crawl索引对三个候选未成功响应。没有取得任何历史对象。
- EPA搜索页检索没有返回可用结果。本记录中的文件名和勘误内容来自官方PDF，不是推测；下载地址状态则只记录为失败尝试。

## 当前准入决定

三份PDF仍只构成官方错误来源线索：0份原工作簿、0份已认证修订工作簿、0个可评分自然错误。下一轮应从EPA对应的专题页面、文档版本索引或其他官方镜像追踪确切URL和归档版本。只有在保留原件哈希、预测锁定早于修订件获取、确认公式及输入对应关系并取得独立公式真值后，才进入自然开发集；这些来源不能进入最终验证集。
