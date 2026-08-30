# V5-PSL 原创性与主张边界

状态：候选冻结前硬门，**已按 v3 通过**。截至 2026-08-30，原登记的 13 篇主文献中
11 篇已完成全文核对，2 篇作为封闭访问直接邻居永久披露但不计全文。此次访问修订
发生在公开压力运行和候选锁之前；边界见 `V5_PSL_LITERATURE_GATE_AMENDMENT_V3.md`，
进度和仓库外证据哈希见 `V5_PSL_LITERATURE_GATE_PROGRESS.json`。

本矩阵只约束可说和不可说的内容，不用“没有检索到”证明原创，也不把多个已有部件
的组合自动称为创新。检索综述只用于发现文献；方法事实必须由下列主文献支持。

## 1. 先固定 V5-PSL 的研究任务

V5-PSL-dev1 的输入是一个可计算工作簿及其可见公式和值，不接受以下信息：

- 期望输出值；
- 输出正确/错误标记或通过/失败测试；
- 用户指定的失败单元格、源错误格、正确公式或错误类型；
- 第三方确认集的标签。

它输出所有公式单元格的完整源排名，以及 `localized`、`review`、
`abstain_unidentifiable`、`unsupported` 四种行动状态。它研究的是固定输入扰动下
的角色条件响应、定向下游恢复和显式非行动规则。它不是通用公式修复器、形式因果
识别器，也不能仅凭内部一致性证明某个公式在业务语义上错误。

## 2. 逐篇主文献矩阵

| 研究线 | 主文献与全文状态 | 原文已建立的内容 | V5-PSL 重叠与禁止表述 | 仍可检验的窄差异 |
|---|---|---|---|---|
| Spreadsheet ambiguity | Dou, Cheung, Wei 2014，DOI `10.1145/2568225.2568316`，已核全文 | AmCheck 识别 cell array，以约束和现有值/公式恢复共同 formula pattern，检测 ambiguous computation smells 并生成修复 | 不得声称表格歧义、公式模式恢复、cell-array 异常或合成修复是新发现 | AmCheck 的歧义是同一 cell array 内公式语义不一致；可检验 V5-PSL 的非行动状态是否能表示“扰动证据无法隔离单一源”，但不能据此声称首次形式化歧义 |
| Metamorphic spreadsheet testing | Poon, Liu, Chen 2017，DOI `10.4018/JOEUC.2017040102`，已核全文（作者接受稿） | 以应用特定 MR 从源输入生成后续输入，不依赖两次执行的期望输出，以 MR 违背检测表格失败；五个含真实开发错误的 EUSES 表覆盖六类错误，实验含五名参与者、43 个 MR 和 570 次执行 | 不得声称首次把蜕变测试、源/后续测试对、无期望输出检测或输入变换用于电子表格 | 该研究由参与者为每个应用识别 MR 并评估是否暴露失败；可检验 V5-PSL 的固定角色条件扰动、完整源排名、定向下游恢复和显式 1/5/0 行动契约 |
| Metamorphic spreadsheet testing | Yang, Hu, Ma 2026，DOI `10.1016/j.infsof.2026.108074`，已核全文（SSRN 完整预印本） | SEDMR 提取 cell array，定义七类值/公式模式 MR 和十种检测方法，组合 CACheck 并标记错误格；在 100 个 EUSES 与 60 个 Enron 表、2,894 个真实及注入错误格上报告 precision/recall/F1 | 不得声称无 oracle 表格检测、输入或公式模式扰动、蜕变关系组合、cell-array 角色结构、错误格标记或 EUSES/Enron 蜕变评测是新方法 | 可检验 V5-PSL 的完整源排名、定向下游恢复、可识别性状态和固定复核预算；这些差异必须由匹配比较证明，不能仅从术语推断 |
| Invariant-based testing | Roy, van Deursen, Hermans 2018，DOI `10.1109/QRS-C.2018.00046`，已核全文 | 用 Daikon 推断不变量，将其变成条件公式测试，在 8 个表上检测回归变异；召回随表和故障类型显著变化 | 不得声称表格不变量、内部关系、违反一致性或不变量测试是新方法 | V5-PSL 不从历史正确版本训练 Daikon 不变量，也不增加 test sheet；可把响应一致性限定为固定证据族之一 |
| Domain invariants | Wang, Zhao 2021，DOI `10.1109/APR52552.2021.00012`，全文不可得披露 | IEEE、Crossref 和 OpenAlex 确认该两页论文为封闭访问；出版方摘要确认其把领域不变量与形式/预测方法结合，用于表格错误检测和修复 | 不得声称领域不变量用于表格调试是新方法，也不得用无法取得全文来支持 V5-PSL 的原创或优越性 | Roy 2018 作为该方向的必核全文锚点；除非以后取得合法全文，否则不允许与 Wang 2021 作实现级差异比较 |
| Formula-role outliers | Cheung et al. 2016，DOI `10.1145/2884781.2884796`，已核全文 | CUSTODES 以公式 AST、引用等强特征和布局、标签、样式等弱特征做两阶段聚类，把少数离群单元格排序为 smell | 不得声称公式角色、AST/引用聚类、布局特征、少数派离群或 smell 排名是新方法 | 可比较静态 cluster outlier 与固定扰动后的角色条件响应，但静态角色稀有度只能作为既有先验 |
| Formula-role outliers | Barowy, Berger, Zorn 2018，DOI `10.1145/3276518`，已核全文 | ExceLint 用相对 reference vectors/fingerprints、矩形区域和熵变化，在无用户真值下排序疑似公式及候选修复 | 不得声称无真值公式检测、相对引用指纹、矩形公式区域、候选修复或人工审查排名是新方法 | 可检验动态响应与定向传播证据相对 ExceLint 类静态排名是否增加源定位信息 |
| Formula-role outliers | Li et al. 2019，DOI `10.1109/QRS.2019.00030`，已核全文 | WARDER 以单格、多格、整簇 validity properties 修正 CUSTODES 聚类，再检测 missing/inconsistent formulas | 不得声称 validity-based 聚类修正、缺失公式检测或不一致公式检测是新方法 | 可把 WARDER 类证据作为静态基线，检验响应条件化和选择性行动的增量，而非重命名其 validity |
| Spreadsheet fault localization | Hofer et al. 2013，DOI `10.1007/978-3-642-37057-1_6`，已核全文 | 将 SFL、SENDYS 和 constraint debugging 适配到表格；用依赖锥和输出正确性/期望输出定位并排名可疑单元格 | 不得声称 spreadsheet fault localization、依赖锥根因排名、suspiciousness ranking 或“定位而非检测”本身是新任务 | V5-PSL 的可检验输入差异是完全不接收 expected output、pass/fail token 或用户标记的失败格 |
| Spreadsheet fault localization | Jannach et al. 2019，DOI `10.1007/s10515-018-0250-9`，已核全文 | 把表格分成 fragments，生成/标注较小测试，按故障概率代理排序，并把带期望结果的测试交给 model-based debugging | 不得声称通过排序减少人工检查、fragment review 或 human-in-the-loop debugging 是新方法 | 可比较无输出标签的单格完整排名与需要用户给出正确/错误结果的 fragment 测试，并单独报告人工审查成本 |
| Mutation/intervention | Hofer, Wotawa 2013，DOI `10.1109/ISSREW.2013.6688892`，全文不可得披露 | IEEE、Crossref、OpenAlex 和 Semantic Scholar 均未提供开放全文；出版方摘要确认其把 genetic-programming automatic repair 适配到电子表格并报告初步修复率 | 不得声称候选变异、遗传编程表格调试、自动表格修复或修复搜索是新方法，也不得用无法取得全文来支持原创或优越性 | Fariha 2020 作为干预调试方向的必核全文锚点；除非以后取得合法全文，否则不允许与 Hofer 2013 作变异体、适应度或搜索机制比较 |
| Mutation/intervention | Fariha, Nath, Meliou 2020，arXiv `2003.09539`，已核全文 | AID 从成功/失败执行日志构造 predicate 候选，以故障注入和自适应 group testing 做干预，定位根因并生成因果路径 | 不得声称 interventional debugging、counterfactual root-cause reasoning、主动干预或因果解释路径是新方法；不得把 V5-PSL 自动称为因果识别 | V5-PSL 是单工作簿、固定输入扰动、无成功/失败执行标签的操作性响应证据；其效果必须由预注册比较而非因果术语证明 |
| Selective prediction | Geifman, El-Yaniv 2017，arXiv `1705.08500`，已核全文 | 形式化 reject option、coverage、selective risk 和 risk-coverage curve，并讨论把拒绝样本交给专家 | 不得声称拒绝预测、弃权、risk-coverage 或把低置信案例交人工是新方法 | 可把这些已有概念实例化为表格源定位的 1/5/0 审查预算，并报告覆盖、风险和人工成本 |

## 3. 绝对禁止的主张

无论后续实验结果如何，以下表述都不能使用：

- “首个无真值电子表格错误检测方法”；
- “首次用输入扰动、蜕变测试或内部关系检测电子表格错误”；
- “首次进行电子表格故障定位或根因排名”；
- “首次发现公式角色、公式族、离群公式或矩形公式区域”；
- “首次把反事实、变异或因果干预用于调试”；
- “首次引入弃权、选择性风险或人工复核预算”；
- “现有工作都只能检测症状，不能定位源”；
- “世界上没有相同方法”“填补空白”“首次证明”等没有系统综述和严格证据支持的句式；
- 在未运行原作者实现时声称“超越 SEDMR、ExceLint、CUSTODES 或 WARDER 原工具”；
- 把内部一致性恢复直接写成真实业务语义修复或形式因果效应。

## 4. 当前可辩护的研究问题

门禁完成后仍只建议使用可证伪、非排他的表述：

> 我们预注册并评估一种用于静默公式源定位的组合：在不提供期望输出、通过/失败
> 标记或用户指定失败格的条件下，比较同角色公式对固定输入扰动的响应，结合定向
> 下游恢复生成完整源排名，并在证据不足时进入复核、弃权或不支持状态。

这句话描述研究对象，不声称该组合必然原创或优于已有方法。论文贡献必须落在实际
通过的比较和消融上，例如：

1. **输入契约**：与 Hofer/Jannach 的 truth-assisted debugging 分开报告；
2. **证据对象**：与 CUSTODES/ExceLint/WARDER 的静态角色离群、与 SEDMR 的 MR
   关系检测逐项比较；
3. **决策契约**：把完整排名与 1/5/0 行动预算分开，报告 coverage、selective risk、
   有害行动率和人工成本；
4. **失败边界**：公开 `abstain_unidentifiable`、`unsupported`、合法例外和求值
   不支持案例，而不是只展示可定位样本。

## 5. 文献门完成条件

v3 门禁要求 11 篇可获得主文献全部满足 `evidence_scope=full_text`，并要求 Wang 2021
和 Hofer 2013 以 `evidence_scope=full_text_unavailable_disclosed` 保留检索记录、出版方
证据哈希、外部可用性笔记哈希和保守禁止主张。两篇披露来源不能支持原创或优越性，
但各自研究方向已有 Roy 2018 和 Fariha 2020 的必核全文锚点。

当前回执为 `11 required full texts verified plus 2 closed-access disclosures`，
`unresolved_sources=[]`、`unresolved_claims=[]`，并绑定本文件 SHA-256，因此 v3
`passed=true`。这不是 `13/13` 全文核对；若以后取得合法全文，必须先补充核对再作
任何实现级比较。

2024 年的 spreadsheet QA literature review 只作为检索导航，不能代替上述主文献
全文。任何新增的直接邻居都可以追加到回执；门禁允许一个研究方向包含多篇原文，
但不能删除原登记的 13 篇记录或把两篇不可得披露改写成已核全文。
