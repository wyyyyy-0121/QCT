# 2026-10-15 恢复研究记录

用户指令：现在继续。此前GitHub上传已核实，当前恢复研究，原有暂停记录保留为历史。原论文源码和预测锁未变，所有本次新增位于 `New version`。

## 结果与证据边界

dev2、dev3在旧39表上都输出13,156项建议，全部与已标注正确公式匹配；16,577个错误格中正确修复13,156格，覆盖79.36297%。相对原论文模型，精确率从65.96%提高至100%，覆盖从78.28%提高至79.36%，仍未通过开发覆盖目标。这是已揭示、窄业务模板的开发结果。

dev1漏修8,515格、误改31个正确格。逐例审计见 `development/selector_dev1/FAILURE_AUDIT.json`。dev2漏修3,421格、该旧集误改0格，见对应 `FAILURE_AUDIT.json`。3,421漏修由3,021个收入系数变化和400个税率符号变化组成，不能依照已知答案直接增加特例补丁。

## 新增压力检查

8个开发微型案例均采用5张声明平行的工作表、每表24个输出公式。原模型通过冻结适配器和实际StructuralGuard/FormulaGuard组件运行；dev2沿用其真实候选。预测过程禁止打开truth/评分/场景登记文件，锁定后由另一进程评分。开发者已知道构造规则，因此这些程序隔离不使案例变成未见验证。

| 开发案例 | 已标注错误数 | 原模型错误建议 | dev2错误建议 | dev3错误建议 | dev3正确修复 |
|---|---:|---:|---:|---:|---:|
| 整列费用符号错 | 24 | 0 | 0 | 0 | 24 |
| 单格漏扣运费 | 1 | 0 | 0 | 0 | 1 |
| 有文字说明的合法免运费 | 0 | 1 | 1 | 0 | 0 |
| 有文字说明的合法折扣豁免 | 0 | 24 | 24 | 0 | 0 |
| 合法收入系数 | 0 | 24 | 0 | 0 | 0 |
| 同样输入但外部规则不允许该系数 | 24 | 0 | 0 | 0 | 0 |
| 未知输出角色的符号错 | 24 | 0 | 0 | 0 | 0 |
| 有文字说明的合法成本报销 | 0 | 24 | 24 | 0 | 0 |

两个收入系数案例输入SHA-256相同，评分真值根据不同外部业务规则设定。这一对用于诊断信息不足，不作为可合并的准确率样本；没有把相反真值塞入最终验收集。dev2及原模型在这对相同输入上分别产生完全相同预测。

dev3对显式业务说明标记及相邻文字采取整表复核，避免忽略说明后自动认定表头方向。其限制是复核范围可能过宽、尚未理解规则、未标记例外仍可能被误判。不能把零建议的精确率写成100%。

随后补建并运行4个代价检查案例，输入和原模型/dev2/dev3真实预测再次独立锁定：

| 代价检查 | 错误数 | dev3正确修复 | dev3错误建议 | 解释 |
|---|---:|---:|---:|---|
| 业务说明与真实符号错误同表 | 24 | 0 | 0 | 24项建议被整表复核，覆盖0%，暴露保护过宽 |
| 无标记的合法免运费 | 0 | 0 | 1 | 未识别例外，误改正确格 |
| 无标记的合法成本报销 | 0 | 0 | 24 | 未识别例外，误改正确格 |
| 备注在另一工作表，目标表符号错 | 24 | 24 | 0 | 复核未扩散至无说明的目标表 |

因此dev3仍未解决业务例外识别。上述25项误建议和24项新增漏修必须进入后续开发回归，不能仅报告前8例零误建议。完整代价证据见 `development/policy_tradeoff_dev1/score.json`；12个案例都不计最终新家族。

## dev4受控规则实验

在独立新增文件中实现4类完整规则语句识别：指定行不计运费、指定表折扣不适用、指定表成本报销为额外收入、指定表普通运费由卖方承担。第一类限定行号，其余限定工作表和角色；其余表头方向仍为假设。未知语句复核，规则不授权的建议复核，原始输入不修改。

dev4沿用已锁定dev2预测，重新读取工作簿可见说明。39旧表、8压力例、4代价例全部重新锁定，再评分。39旧表结果不变；8压力例误建议0；代价例p01的24项真实符号错误恢复，p04仍修复24格。p02/p03未标记例外的25项误建议仍存在。系数歧义和未知输出角色仍漏修。

这是开发阶段按已知规则措辞设计的受控解析实验，不是自然语言规则理解验证；不能以它替代不同业务域/措辞的新开发检查，也不能借它给旧表添加答案派生契约。dev4第一次预测源码锁漏列导入的policy_notes依赖，在读取评分答案之前保留到 `development/selector_dev4_lockdraft`，未评分、不作为权威结果。补全依赖后重新锁定，权威证据为 `development/selector_dev4/`。原dev3源码/预测锁未修改。

## 来源排查

metadata_v3至v5保留请求地址、获取时间、内容哈希和访问失败。原始第三方网页本地保留，Git忽略正文但保留RECEIPT摘要。

- 18F固定commit许可API返回的LICENSE.md正文明确CC0，不再只依据NOASSERTION自动标签。
- Packt固定commit许可正文为MIT，仍需审查工作簿第三方内容。
- RenewablesPro README声明CC BY-NC-SA 4.0，但固定tree只有README和xlsx，没有所链接LICENSE；保留此缺口。
- EPA官方目录存在6组勘误/修订入口及计算工作簿。仅看到了链接；没有阅读勘误或认定每组均为自然公式错误，也没有取得错误历史版本。
- 英国TAG官方页及DESNZ 2023发电成本官方页可访问，后者含名称带correction的LCOE工作簿链接。仅凭文件名不能认定为可评分自然公式错误。
- Damodaran官方目录和主页可访问；明确再利用条款和模板去重仍待查。
- 新西兰Treasury请求403；若干旧官方URL404；NIST更正后的建筑全生命周期成本软件页可访问，但未发现可纳入的公式工作簿证据。

优先候选按6个作者/机构来源组登记。英国政府的两个部门入口暂合并一组；同一站点的多个表、多个勘误不各算一个来源。候选来源独立性及历史使用审计未完成，合格数保持0。

## 可复现命令

以下命令已执行，程序对已有预测目录拒绝覆盖。复核现有结果应检查哈希和读取报告；重跑请在另建目录登记。

```text
python scripts/audit_dev1_failures.py
python scripts/run_selector_dev2.py predict
python scripts/run_selector_dev2.py score
python scripts/audit_dev1_failures.py --run selector_dev2
python scripts/run_semantic_stress_dev.py prepare
python scripts/run_semantic_stress_dev.py predict
python scripts/run_semantic_stress_dev.py score
python scripts/run_selector_dev3.py predict
python scripts/run_selector_dev3.py score
python scripts/run_policy_tradeoff_dev.py prepare
python scripts/run_policy_tradeoff_dev.py predict
python scripts/run_policy_tradeoff_dev.py score
python scripts/run_selector_dev4.py predict
python scripts/run_selector_dev4.py score
python -m unittest discover -s tests -v
python scripts/discover_source_metadata_v3.py
python scripts/discover_source_metadata_v4.py
python scripts/discover_source_metadata_v5.py
```

Python为 `/home/ayaka/miniforge3/bin/python`。预测和评分分进程，dev3/dev4还核对上游dev2及压力预测的源码/预测锁。测试13项通过。开发输出中review候选保留供复核，计分只认实际propose。完整复核命令为 `python scripts/verify_research_checkpoint.py`。

目标保持active，最终验收未开始。下一研究重点是可核查业务证据和更广业务覆盖，而不是用已揭示答案强行替换系数。

## 本轮跨业务开发检查

新增`development/crossdomain_dev1`，库存结转、贷款摊还、预算分摊、单位转换各8例，共32例。各类包含干净表、孤立错误、整列错误、无标记例外、已标记例外、例外与错误共存、4/5张表共用污染参照、多行表头及多区域汇总布局。库存和贷款含公式依赖链，预算含范围求和及绝对引用，温度转换含负数输入和单位。每个正确公式均与独立Fraction业务算术计算结果核对；每个实际输入求值无报错，注入公式仍能正常计算。

原模型适配器、实际StructuralGuard/FormulaGuard、dev4均运行，完整依赖与32份预测先锁定，另进程才读取答案。输入索引不包含场景名称、错误位置或正确公式。所有工作簿、公式和错误全量计分，正确格误建议计入分母，review不算修复。

| 四类开发案例合计 | 实际建议 | 正确 | 错误 | 精确率 | 覆盖率 |
|---|---:|---:|---:|---:|---:|
| 原模型 | 236 | 108 | 128 | 45.76% | 21.95% |
| dev4 | 11 | 8 | 3 | 72.73% | 1.63% |

492个错误中384个为刻意构造的共享污染错误；这些占比不是现实错误发生率，不能外推真实表现。dev4每类修复两个孤立错误；库存、贷款、单位转换各误改一个无标记合法例外。四类整列错误和共享污染错误均未修复。已标记例外没有误建议，但同表真实错误也进入复核。原模型在每类共享污染案例把24个正确格指向多数错误公式，四类共96个有害建议。

原因：dev4方向检查只认识旧财务表头且不支持公式依赖，无法为新领域整列候选提供依据；共享污染时多数候选本身错误；未知说明的整表复核损失覆盖。多区域案例中dev4保护了汇总与不同单位子区域，原模型每例误建议5个正确公式。

这32例是开发者知晓规则的开发诊断，不是新的最终验证，不增加最终家族/来源计数。完整性检查扩展至9组锁；13项既有测试仍通过。命令：`python scripts/run_crossdomain_dev.py prepare`、`predict`、`score`，随后`python scripts/verify_research_checkpoint.py`。

## 本轮额外来源元数据

`metadata_v6/RECEIPT.json`保留8次请求结果。Iowa State官方Ag Decision Maker工具索引可访问，列出207个潜在线索链接；不能按链接数认定模板数。NLR官方JEDI入口可访问，但未验证工作簿下载或许可。其余请求为403、404、405或DNS失败，均保留。仅下载网页元数据，没有取得最终工作簿或自然错误答案。优先候选来源组增加到8，合格数仍为0。

用户追加要求：及时提交并上传GitHub，之后每个可复核研究阶段及时推送。当前阶段目标仍active；上传进度以GitHub分支实际SHA核对为准。
