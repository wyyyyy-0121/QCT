# 新公开来源实查与保留清单（2026-10-18）

本轮优先补数据来源，没有修改模型，也没有新增准确率成绩。已找到六个大学官方计算表目录，并对每个机构至少一个具体下载地址核实了成功响应。它们尚未用于开发，保留为冻结后独立验证的候选。目录、响应头与文件链接不能证明公式真值或模板独立性，因此最终验收合格来源和家族仍为0；“找到候选”和“完成最终验收”从本轮起分开报告。

## 已核实的六个计算表来源

| 来源 | 官方目录中的工作簿链接数 | 具体文件及访问证据 | 预期计算内容 |
|---|---:|---|---|
| Ohio State University | 283 | candidate_02–05 的 HEAD 返回200和Excel MIME | 种植成本、母牛犊牛、育肥牛、绵羊预算 |
| Washington State University | 99 | candidate_06 的 HEAD 为403；一次普通流式GET只检查响应头返回200和xlsx MIME，未读文件正文 | 灌溉苜蓿、果园建立及多年经营、采收方式比较 |
| University of Arkansas | 60 | candidate_10–12 的 HEAD 返回200和xlsx MIME | 机械设备成本、租赁、灌溉作物预算 |
| Purdue University | 1（本次具体文章） | candidate_17 的 HEAD 返回200和xlsx MIME | 多种作物收入、单位成本、盈亏平衡 |
| Kansas State University | 20个唯一链接（两个作物目录共享一个文件；牲畜目录19个） | candidate_18、19、22 的 HEAD 返回200和xlsm MIME；部分其他链接连接中断，照实保留 | 作物、牛肉、绵羊、奶牛及价格表 |
| University of Tennessee | 18 | 固定抽查6个文件，HEAD均200和application/octet-stream；目录链接后缀为xlsm，尚未验证实际文件内容 | 作物、营销决策、母牛犊牛、育成、果蔬及多年蓝莓预算 |

上述机构是初步来源分组，还需要历史重合审计、作者/模板谱系检查。不能把同一文件的不同年度、不同作物或镜像算成独立模板家族。田纳西目录中的烟草预算明确为Tennessee–Kentucky联合项目，后续不可再将Kentucky另计一个独立来源。

引用目录：

- Ohio：<https://farmoffice.osu.edu/farm-management/enterprise-budgets>
- WSU：<https://ses.wsu.edu/enterprise_budgets/>
- Arkansas：<https://www.uaex.uada.edu/farm-ranch/economics-marketing/farm-planning/budgets/crop-budgets.aspx>
- Purdue：<https://ag.purdue.edu/commercialag/home/resource/2024/11/crop-budget-spreadsheet/>
- Kansas：<https://www.agmanager.info/farm-budgets>；<https://www.agmanager.info/farm-mgmt-guides/livestock-budgets>
- Tennessee：<https://arec.tennessee.edu/extension/budgets/>

## 额外候选与访问失败

- NLR JEDI：已实查生物燃料、煤、地热、天然气、输电及风电页面的xlsm链接；具体模型下载地址返回403。目前只确认目录，不能写成已可获取。它们有助于扩展能源领域，但不能仅靠技术名称认定不同模板。
- IPCC TFI：HWP上传模板链接HEAD为200和xlsm MIME。是否含足够的计算公式未知，暂不算作上述六个计算表候选。
- Vertex42：核实贷款摊还、退休测算、工时、甘特图和项目预算的发布页；发布者链接HEAD及贷款链接一次普通GET响应头均403。个人使用条款禁止公开分发原表或衍生表；当前只保存公开元数据，不纳入可获取来源数。
- Nebraska现行预算改用网页ABC程序；本次存档入口链接为PDF，不当作Excel数据来源。
- Michigan、Minnesota、Oklahoma、UC Davis及DairyNZ遇到挑战页或403；HTTP200但显示Incapsula的页面也保留为失败，不当作成功。
- 部分NIST、Cornell、Purdue、NCSU及NLR猜测路径404，均保留请求证据，未据此声称有可用数据。

本轮保留三份具体文件清单，共45条候选链接、9个初步机构标签；其中6个为上述计算表机构，IPCC需核实公式内容，NLR与Vertex42下载尚未成功。所有文件正文均未获取，无法报告公式数、实际家族数或业务错误标签。

## 自然错误标签核查

Reinhart–Rogoff只能作为一个历史案例来源，不按镜像或复现作者重复计数。

1. 已核实Herndon–Ash–Pollin仓库 `michaelaoash/HAP-RR-git` 的main树，根目录树SHA为 `b9c34472da97465050780dae5a4dab9ab7c69a63`，含 `RR-keycolumns.xlsx`、`RR-post1990.xlsx`；仓库元数据声明CC0。README只有一句复现说明，不能证明这两个文件分别是错误原表和正确修订版。
2. 已核实 `scienceetonnante/Reinhart-Rogoff` 的根目录树SHA为 `658bfafcfe19878cf13ffa748d3e5ab8c1969f6b`，含 `RR.xlsx` 和复现notebook。树SHA不是Git提交SHA，不能直接替代raw下载链接中的commit。仓库描述明确提到复现计算与错误；未获取工作簿或notebook答案正文，也未建立逐格修复真值。
3. ExceLint公开代码树含 `Public_debt-ratios_advanced.xlsx` 等测试文件路径，但这不是一个新的独立自然错误来源。其README未提供可直接验收的全建议修复标签。
4. Crossref核实论文题名、Herndon/Ash/Pollin作者与DOI `10.1093/cje/bet075`，期刊为Cambridge Journal of Economics，38(2),257–279；在线发表日期2013-12-24，卷期为2014。书目信息不能代替逐格答案。
5. DataDebug/CheckCell重点是数据错误，不能直接冒充静默公式修复标签。Tasi/Spreadsheet Error Dataset仍为此前已排除的EUSES衍生。搜索得到的课程练习、手工注入或一般数据清洗项目不计自然错误。

自然错误目前未满足标签门槛。下一步需核实错误原表来源、正式勘误或可靠修订证据，以及所有输出建议都能裁定的范围；只找到一个报错例或两个xlsx文件不等于这一门槛已完成。

## 模板机制候选与验证顺序

根据目录可预登记以下机制假设：年度作物成本、牲畜繁育、育肥、饲养管理、灌溉成本、多年果园建立、手工/机械采收、机械使用成本、土地租赁、多作物比较、盈亏平衡、价格汇总、营销决策、后备母牛育成、果蔬生产与多年莓果经营。它们只是待查机制，可能共享模板，不能称为已满足15家族。文件内容未获取，实际家族数为未知。

六个大学来源仍集中于农业经济，不能支持跨所有电子表格领域的普遍性结论。能源、气候及其他计算机制继续扩展；不以六个目录代替领域和模板独立性。

1. 先完成元数据级历史重合与作者谱系审计，登记保留/排除来源及明确的数据范围；不因为某个模型预计容易做对而挑表。
2. 解决静态读取边界：不少候选为xlsm/xls，而论文原适配器目前拒绝这些扩展名。冻结前决定公平的静态快照适配和失败记录规则；不运行宏，不把拒绝项悄悄删掉。上传模板也可能没有公式，不能提前计为可评分工作簿。
3. 冻结原模型适配、改进模型、候选选择、注入机制、纳入规则和评分器，之后才获取最终工作簿及修订答案。注入保留原式和日志；来源原公式不能未经核查就全视为业务正确。
4. 冻结后检查公式、去重模板，保留支持失败与弃答；若无法满足六来源十五家族或自然错误标签门槛，继续补充未见来源。先锁全部预测，另进程揭示答案评分。

## 可复核证据

- `expansion_20261018_v2`至`v8/RECEIPT.json`和各自pages：目录、失败、树与书目信息；v1因相对路径处理错误未完成提取，由v2替代，不能用v1支持目录计数。
- `RESERVED_SOURCE_CANDIDATES_20261018.json`、`RESERVED_ADDITIONAL_CANDIDATES_20261018.json`、`RESERVED_TENNESSEE_CANDIDATES_20261018.json`：具体链接和目录哈希。
- `CANDIDATE_HEADER_RECEIPT_20261018.json`、`ADDITIONAL_HEADER_RECEIPT_20261018.json`、`TENNESSEE_HEADER_RECEIPT_20261018.json`：HEAD响应，不读取工作簿正文。
- `GET_HEADER_FALLBACK_RECEIPT_20261018.json`：四项普通GET仅取响应头，WSU成功，另外三项403。未读取或保存任何工作簿正文。
- `PUBLICATION_REDACTIONS_20261018.json`：GitHub推送保护发现两个NIST 404网页快照中的网站令牌格式字符串。公开快照已脱敏，原始抓取仅在本地排除目录保留；回执分别保存原始下载与公开快照哈希。脱敏未改变目录结论，也未绕过推送保护。

本轮不增加最终合格来源/家族数，也不产生新的模型性能指标；它完成了此前缺失的具体来源定位与下载入口预查，避免继续只在作者编写的小样例中迭代。
