# 自然错误出处与农业以外来源补充（2026-10-18）

本轮新增25次目录/出处元数据请求，保存21份响应；另检查14个下载链接的HEAD响应，10个成功。没有读取候选工作簿、ZIP档案或修复答案正文，最终合格来源和家族仍为0。来源台账同步更新，七个已用于开发的来源继续整体排除。

## Reinhart–Rogoff自然错误案例

找到UMass PERI作者机构的[研究页面](https://peri.umass.edu/publication/does-high-public-debt-consistently-stifle-economic-growth-a-critique-of-reinhart-and-rogoff/)，页面列出论文、技术附录、数据/代码ZIP档案、变量对照和RR-keycolumns工作簿。新站两个工作簿、两个代码档案HEAD均返回200；旧fileadmin工作簿路径410。成功响应只证明链接可响应，不证明原始错误工作簿或逐格真值已经存在。

Reinhart本人[Debt and Growth页面](https://carmenreinhart.com/debt-and-growth/)给历史41_data.xlsx链接的上下文明确为：“Our correction to our 2010 paper is available here and here.” 因此此Excel必须列为更正候选，不能冒充原始错误表。归档HTTP链接本次超时，没有取得正文。

复现README声称的Dropbox Original data本次HEAD连接重置；已固定commit的scienceetonnante/RR.xlsx入口HEAD超时，均不能写成已可下载。HAP、scienceetonnante、PERI、Dropbox和作者更正仍只对应同一个历史案例，不能按网站或镜像计多个来源。原表/修订真值配对未验证，尚不能进入最终自然错误验收。

## 两个新的非农业候选来源

| 来源 | 从目录提取的候选 | HEAD结果 | 尚未证明 |
|---|---|---|---|
| Excel Easy | 贷款摊还、预算、资本投资，共3个xlsx | 3/3为200及xlsx内容类型 | 来源历史无重叠、模板独立性、原式正确性和许可 |
| NSW Treasury | Rapid CBA、Employment Calculator、Outcome Values Database，共3个xlsx | 3/3为200及xlsx内容类型 | 数据库是否含公式、模板独立性、原式正确性和完整纳入范围 |

Excel Easy为教程型来源，不能替代真实业务工作簿的代表性。NSW工具目录由其Treasury指南链接到NSW政府新站，按一个机构来源分组。不同工具名称不自动计为独立模板家族。

其他尝试均保留：GHG Protocol与NZ Treasury返回403挑战页，CDC两个入口403，WHO猜测路径404，Contextures418，NRCS超时、USACE域名解析失败、Google查询超时。NOAA地址200但落到Digital Coast页面且没有工作簿链接，不计为成功计算器来源。澳大利亚OIA指南本身无xlsx，通过其NSW指南链接才找到具体工具目录。

## 可复查证据

- v11/v12/v13索引与响应：`expansion_index_20261018_v*.json`及相应目录；原v2–v10记录不修改。
- 原始链接与角色：`RESERVED_NEW_DOMAIN_NATURAL_LINKS_20261018.json`、`RESERVED_NSW_RR_PINNED_LINKS_20261018.json`。14条包括ZIP、修订及数据对照，不能统称14个自然错误工作簿。
- HEAD回执：`NEW_DOMAIN_NATURAL_HEADER_RECEIPT_20261018.json`、`NSW_RR_PINNED_HEADER_RECEIPT_20261018.json`。
- 离线审计：`../qa/SOURCE_EXPANSION_V11_V13_AUDIT_20261018.json`，核对索引、保存页面哈希/字节数、HEAD方法及零正文读取；54个文件凭据模式检查无发现。

下一步保留这些候选，查清原案例与修订对照的可用性、许可及历史使用；最终模型、评分与纳入规则冻结后才取得工作簿。元数据预查允许继续推进，不能把“未获取正文”解释为已完成数据验收。
