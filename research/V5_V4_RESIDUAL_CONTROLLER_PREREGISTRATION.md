# FormulaGuard V4 残差风险控制器预注册

日期：2026-08-31  
协议：`formulaguard_v4_residual_controller_v1`  
研究代号：`V4-RRC`（V4 Residual Risk Controller，不是正式版本名）  
状态：在任何控制器实现、交叉拟合评分、旧试用包读取或保密数据访问前冻结

## 1. 研究问题与边界

`V4-R1` 仍是唯一冻结主排序器。Gate 2 的四个无标签通道作为完整排序器时在 Enron
和 Modified EUSES 退化；DRFV、FCRL 和 VHRL 又分别在语料或代理覆盖门停止。因此
`V4-RRC` 不再尝试替代 V4 的完整排序：V4 第 1--4 位永不改变，模型只能保留原第五位，
或把一个既有 `peer` 候选放到第五位。

已揭晓上限审计显示，单独 `peer` 在固定五格 oracle 下有 +31.18pp 总体空间和
+22.67pp Enron 空间。该数字只证明候选存在，不证明可识别。V4-RRC 的可证伪问题是：

> 不读取标签、语料身份或模板身份时，一个按结构组交叉拟合的低复杂度控制器，能否
> 识别少量有正残差收益的第五位替换，同时保住 V4 已命中事件和干净控制？

若不能同时得到至少 5pp 的 Top-5 增益和预注册的控制安全，本线终止。不得把 oracle
上限、交叉拟合开发成绩或拒绝选项本身写成原创算法。

## 2. 先验工作与允许贡献

必须作为先验工作引用、不得声称原创的内容包括：

- ExceLint 的相对引用指纹、异常区域与修复候选；
- CUSTODES/WARDER 的公式聚类和离群检测；
- V4 的图、模式、行为和反事实证据；
- 线性/岭回归、Reciprocal Rank Fusion；
- Geifman and El-Yaniv (2017) 的 selective prediction、coverage 和 risk-coverage；
- Bates et al. 的 distribution-free risk-controlling prediction sets，以及一般 conformal
  risk control。若论文使用“风险控制”术语，必须说明本研究的小样本经验校准不自动
  获得分布无关保证，除非相应条件和有限样本界另行严格实现并验证。

允许检验的窄贡献只有：**在冻结 V4 五格审查预算下，把既有表格异常候选转化为可
弃权的单格残差责任决策，并同时度量新增命中、V4 损失和控制行动风险。**

## 3. 数据角色与禁止输入

### 3.1 交叉拟合开发

只读取已提交的 Gate 2 公开开发工件：

- `results/model_discovery_gate2_final_v3/event_scores.jsonl`；
- `results/model_discovery_signal_audit_observed/` 的完整无标签信号分片；
- `results/model_discovery_v4_baseline/` 的冻结 V4 分片；
- 对应的 190 个错误、30 个控制标签只进入训练目标、校准和评分器。

这些数据已经揭晓；五折交叉拟合只限制直接同组泄漏，不把它们变回独立验证。一个
`unit_id` 有多个事件时只能生成一个推理决策，所有同工作簿事件必须在同一外层折。

### 3.2 禁止模型输入

模型、阈值和候选选择不得读取或派生以下字段：语料/队列 ID、错误类型、case kind、
源格、正确公式、期望输出、通过/失败位、文件名、工作表名、单元格文字、公式字符串、
公式 fingerprint/shape/role 字符串、原始或缓存值、绝对行列、workbook 哈希、unit ID、
结构组 ID、模板 ID、人员身份和任何保密字段。结构组只用于拆分和宏平均，不是特征。

## 4. 候选和固定五格动作

1. 候选池是 Gate 2 已冻结的 `peer review_cells`，即按 peer 完整排名经区域去重后最多
   五格，再删除 V4 前四位和原 V4 第五位；
2. 若池为空，必须保留 V4；
3. 控制器为每个候选预测残差效用，选择最高者；分数并列时按 peer 名次，再按稳定
   工作表序号/单元格顺序，仅作为最终确定性并列规则；
4. 只有最高分严格超过该外层折的冻结阈值并通过版本保护条件时才替换第五位；否则
   保留 V4；
5. V4 第 1--4 位及第五位以后的相对顺序完全不变。完整输出通过把入选五位的候选移到
   第五位并把原第五位后移一位得到；审查预算仍为五格。

## 5. 固定无标签特征

所有连续特征只用训练折均值和标准差标准化；零方差置 0。缺失数值置训练折中位数并
增加一个缺失位。唯一允许的特征如下，不得在看到结果后增加：

- 归一化 reciprocal rank：候选在 `peer/combined/role/impact/V4` 的名次；
- Top-5 共识位：候选是否进入 combined、role、impact Top-5，共识数量；
- 通道分数：候选的 peer、combined、role、impact 分数及各自与下一名的非负差；
- 原子记录：`equivalence_class_size`、`region_size`、`precedent_count`、
  `dependent_count`、四个 `peer_counts`、`peer_formula_count`、
  `formula_family_count`、`alternative_support`、`second_alternative_support`、
  `independent_support`、`alternative_margin`、`peer_disagreement`、
  `role_outlier_score`、`competition_score`、`defect_score`、`evidence_tier`、
  `impact_only`、`descendant_count`、`sink_count`、`max_depth`、`weighted_reach`、
  `impact_score`、`truncated`；
- 原子状态四个固定 one-hot：`unsupported/ambiguous/evidence_supported/impact_only`；
- V4 数值证据：`formula_anomaly`、`graph_anomaly`、`behavior_anomaly`、
  `legacy_prior`、`rrf_score`、`consensus_rrf_score`、`candidate_support`、
  `candidate_quality`、`local_gain`、`global_harm`、`candidate_delta`、
  `intervention_responsibility_gain`；
- V4 状态六个固定 one-hot：`strong_counterfactual/moderate_counterfactual/`
  `pattern_only/uncalibrated_candidate/no_candidate/not_intervened`；
- 工作簿尺度：`log1p(formula_count)`、可解析/可见/不支持公式比例、
  `log1p(region_count)`，以及候选 region/equivalence/peer-family 数量除公式数；
- 候选与 V4 第五位在上述 reciprocal rank、通道分数、原子数值和 V4 数值上的差值。

`best_alternative`、修复公式、repair hypothesis 内容和公式文本均禁止；修复是否正确
也不得反向成为特征。

## 6. 固定学习器与目标

唯一学习器是带截距的线性 L2 岭回归，使用 NumPy 闭式解；标准化后的斜率惩罚
`lambda=1.0`，截距不惩罚。不使用随机森林、boosting、神经网络、特征选择、交互项、
超参数网格或多 seed 选优。

每个事件-候选训练行的目标是替换相对 V4 的固定效用：

- V4 未命中且替换后命中：`+1`；
- Top-5 命中状态不变：`0`；
- V4 命中但替换后未命中：`-4`；
- 任一 control 上采取替换：`-2`。

同一结构组内事件权重和为 1；同一工作簿的候选决策在所有事件行共享。目标权重体现
“避免破坏 V4”和“避免控制行动”优先于追求总体命中，不得依据结果修改。

## 7. 五折交叉拟合和阈值

`fold = int(SHA256(structure_group)[:8], 16) mod 5`。对外层测试折 `j`：

- 测试：`j`；
- 校准：`(j+1) mod 5`；
- 训练：其余三个折；
- 同一工作簿、结构组和近重复组不得跨折。

训练折拟合标准化和岭回归。校准折枚举预测分数的唯一值作为阈值；一个阈值只有同时
满足以下条件才可选：正残差行动精度至少 75%、control 工作簿行动率不超过 15%、
V4 已命中错误事件损失率不超过 2%，并至少恢复 3 个事件。可行阈值中先最大化结构组
宏净 Top-5 增益，再最大化恢复事件数，再选择行动更少且阈值更高者；无可行阈值则该
折全部弃权并标记校准失败。

每个外层测试折只评分一次。若少于三个折产生有限阈值，开发门失败。全部门通过后，
最终部署模型固定用折 0--3 拟合，并只用折 4 按相同约束选一次阈值；折 4 不进入最终
系数拟合。该模型和阈值在旧试用前提交锁定，不再用五折测试结果选择参数。

## 8. 开发门 D0 与唯一修订 D1

五折外层合并后必须全部满足：

1. 错误结构组宏 Top-5 相对 V4 至少提高 5pp；
2. Enron 相对 V4 至少提高 5pp且 MRR 不下降；
3. Integer、Modified EUSES、Historical 100 任一队列不得下降超过 2pp；
4. 正残差行动精度至少 75%；
5. V4 未命中错误的恢复率至少 15%；
6. V4 已命中错误的损失率不超过 2%；
7. 30 个公开 control 的工作簿行动率不超过 15%；
8. 至少四个外层折的净 Top-5 差值非负，且至少三个折有有限校准阈值；
9. 两个独立进程的特征、折、系数、阈值和预测哈希完全一致。

若 D0 的总体增益已达 5pp、Enron 不低于 V4，但只因第 4、6 或 7 项安全门失败，允许
唯一一次 D1 加严：候选还必须是 `evidence_supported`，且除 peer Top-5 外同时进入
combined 或 role Top-5。D1 使用同一特征、学习器、折、阈值规则和门完整重跑。

若 D0 因增益、Enron、队列退化、覆盖、折稳定或可复现性失败，直接终止；不得用 D1
补覆盖。D1 后任何一门失败也终止。不得修改 lambda、效用权重、特征、候选 Top-k、
阈值、折或门槛。

## 9. 固定基线和消融

同输入必须报告：未改 `V4-R1`、`V4.2-Review-B` 原生可空第六位、V5-PSL static
anchor、Gate 2 fixed selector、`RRF(V4, peer, k=60)`、强制 peer Top-1 第五位替换，
以及 oracle 上限。ExceLint 只按原生 region hit 和审查格成本报告，不把区域输出伪造
成完整逐格排名。V4.2 的六格成本不能伪装成五格成绩。

固定消融为：无 V4 数值证据、无原子数值证据、无跨通道共识、无风险阈值（所有正分
均行动）和只有 peer reciprocal rank。消融不参与候选选择，也不能推翻主门。

## 10. 候选锁和旧 revealed-trial

D0 或 D1 全部通过后才提交候选规格、源码、配置、特征顺序、系数、标准化统计、阈值、
环境、开发预测和哈希锁。随后旧非保密 `240+120` 包只按既有
`V5_SUCCESSOR_REVEALED_TRIAL_PROTOCOL.md` 接收并运行一次；它永久是 revealed-trial，
不是独立外部验证，也不能触发模型修改。

除设计完整性外，旧试用必须达到：Top-5 相对 V4 至少 +5pp、正残差行动精度至少
75%、V4-miss 恢复率至少 15%、V4-hit 损失率不超过 2%、control 行动率不超过 15%，
且至少 80% 模板组方向不与总体增益冲突。失败即终止，不访问新保管人数据。

## 11. SpreadsheetBench 2 公开锁后验证

旧试用通过后，候选仍不可改变。按固定 revision 接收 SpreadsheetBench 2 的 100 个
Debugging input；先做训练侧重合删除并按相同配置重拟合一次，gold 保持未物化。对
所有 input 写出 V4-RRC、V4、V4.2、static anchor、fixed selector、RRF 和 ExceLint
原生输出，完整预测锁提交后才物化 gold。

若重合删除改变了折 0--3 的训练成员，只允许按原折和原配置机械重拟合，并仍以折 4
选择阈值；随后必须用最终权重重算并提交全部既有公开输入预测。不得依据旧试用标签或
SpreadsheetBench 2 input 内容改特征、效用、门或算法。

主要任务、公式差异真值、结构组、precision@5/hit@5/MRR/AP 和控制重跑沿用
`V5_DRFV_MECHANISM_SELECTION_AND_PREREGISTRATION.md` 的 U2 定义。至少 50 个合格
任务、30 个结构组；V4-RRC hit@5 相对 V4 至少 +5pp，结构组 bootstrap 95% 下界大于
0，V4-hit 损失率不超过 2%，gold-correct control 行动率不超过 15%，且至少 80% 结构
组方向不冲突。失败即终止；SpreadsheetBench 2 不降级为调参集。

## 12. 保密 `240+120` 一次评估

只有开发门、旧试用和 SpreadsheetBench 2 全部通过，并且最终候选规格、源码、配置、
系数/权重、环境和**全部公开输入预测锁**均已提交后，才允许访问
`/home/ayaka/code/FormulaGuard_240_120/`。此前禁止列目录、哈希、读取、抽取、重合
审计或 schema 探测。

用户已授权条件满足后由 Codex 直接一次执行，无需再等消息。接收器按既有 240-error /
120-control 协议 fail closed；设计不符则只报告不符，不为适配包修改模型。正式门为：
V4-RRC Top-5 相对 V4 至少 +5pp、结构组 bootstrap 95% 下界大于 0、正残差行动精度
至少 75%、V4-miss 恢复率至少 15%、V4-hit 损失率不超过 2%、control 行动率不超过
15%，六类错误任一类不下降超过 5pp，至少 80% 模板组方向不冲突。

结果无论成败均提交回执，模型不再修改。全部门通过前不得命名 `V5-R1`；即使通过，
若最终包是专家注入错误，也只能支持未见注入模板上的结论，不能自动外推自然业务错误。
