# V5-AETR 独立完整排序可行性预注册

日期：2026-09-01  
协议：`formulaguard_aetr_crossfit_v1`  
研究代号：`AETR`（Atomic Evidence Transfer Ranker，不是正式版本名）  
性质：揭晓公开开发集上的监督式跨结构/跨语料可行性检验

## 研究问题

Peer 第五位残差路线已经在五种特征视图的嵌套结构折中全部失败。该失败不能回答另一个
问题：不继承 V4 最终排名，直接从全部公式的无标签原子证据学习完整排序，是否能在未见
结构和未见语料上稳定超过 V4。

AETR 是一次独立全排序检验，不是 V4 控制器。它不使用 Closure、Responsibility、输入
扰动响应、修复结果或 V4 名次作为特征。若本轮失败，不允许把结果改造成新的第五位阈值，
也不访问保密 `240+120`。

## 原创性与已有工作边界

Ridge、监督式 learning-to-rank、分组交叉验证、公式异常分数、角色聚类和完整排名都不是
本项目首创。AETR 只有在结果成立后才允许检验以下窄贡献：把 FormulaGuard 的“替代支持、
制度竞争、角色异常和传播影响分离”原子证据，通过错误单元和结构组均衡的可解释线性头
映射为完整公式排名，并验证它是否跨模板和跨语料迁移。若结果只在同语料交叉验证成立、
leave-one-corpus-out 失败，则不能称为可迁移主模型。

## 冻结输入与禁止输入

- 196 个 observation profiles：
  `26f7d1d64a65860fb90714a51beb602742d28d1cfefeea8cbadf331b0e1463dc`；
- 220 个公开事件表：
  `c68e2436957a83f6e8e80e6de6c5a3d45ca35b71e162ebc928275352ba90dd34`；
- Peer 原子审计合并分片：
  `17fab17b109376e22d339a25d3861aa8c72e5c05a2c410cceab1845938a93890`；
- V4 合并分片只允许在全部 AETR 排名形成后作为评分比较：
  `b6ad4b46058e7c5b966bd8faa4b790f52c33a87fa03631fa744fe4a1df28d1f6`。

模型输入禁止包含 V4 名次/状态/分数、V4 第五位差值、Closure、Responsibility、事件来源
格、正确公式、错误类型、case kind、cohort、structure group、unit ID、文件名、工作表
文字、格地址或公式原文。保密 `/home/ayaka/code/FormulaGuard_240_120/` 不得列举、哈希
或读取。

## 固定特征

每个公式只从已锁定的 Peer 原子审计构造：

1. `rr_peer/combined/role/impact`；
2. 四通道各自的 `score` 和相邻 `margin`；
3. 原子数值：equivalence/region 大小、precedent/dependent、四类 peer count、
   peer-formula/formula-family 数、两级 alternative support、independent support、
   alternative margin、peer disagreement、role outlier、competition、defect、evidence tier、
   impact-only、descendant/sink/depth/weighted-reach/impact 和 truncated；
4. 工作簿公式/可解析/可见/unsupported/region 比率与候选 region/equivalence/peer-family
   比率；
5. Combined/Role/Impact Top-5 和三者共识数、四种原子状态 one-hot。

明确排除所有 `candidate_minus_fifth_*`，因为第五位由 V4 定义。连续特征只在训练折拟合
中位数、均值和尺度，并增加 missing indicator；离散/one-hot 保持原值。实现必须把精确
字段顺序写入回执。

## 固定学习器与权重

主模型为带截距 closed-form NumPy ridge，`lambda=1.0`，目标为来源公式 `1`、其他公式
`0`。同一错误工作簿的多个事件先取来源格并集，避免复制同一完整排名。每个训练结构组
总权重相同；组内错误工作簿等权；每个工作簿的正类总权重和负类总权重各占一半。控制
工作簿没有来源标签，不进入训练。

模型对工作簿全部公式输出分数。排序键依次为模型分数、Peer 名次、Combined 名次、Role
名次、Impact 名次和原始公式清单顺序；后五项只解决精确分数并列，不进入 ridge 特征。
不搜索正则、特征子集、类别权重、随机种子、Top-k 或排序阈值。

## 固定外推设计

### 结构五折

使用冻结 `structure_fold`。每轮四折训练、一折测试；训练与测试结构组严格不交叉。五轮
合并后，每个事件恰有一次外折完整排名。

### Leave-one-corpus-out

分别留出 `enron`、`historical_100`、`public:integer_corpus`、
`public:modified_euses` 和 `public:info1`。训练不得包含留出 cohort，也不得包含与其共享
结构组的成员。Info1 只有两个事件，只报告，不参与硬门。

## 四项固定消融

主模型固定为 `full`，消融不得替代主模型：

1. `rank_only`：只保留四通道名次、分数、margin 和 Top-5 共识；
2. `evidence_only`：去除四通道名次/分数/margin，只保留原子证据、尺度和状态；
3. `no_workbook_scale`：从 full 删除工作簿及候选尺度/比率；
4. `formula_micro_weighting`：保持 full 特征，但训练公式行等权，不做结构组/工作簿/
   正负类均衡。

同时报告冻结 Peer/Combined/Role/Impact 原始完整排名与 V4，不从这些基线选择新模型。

## 主要指标与公开门

主要口径为结构组宏 Top-5 和 MRR；以结构组为单位、种子 `20260901` 做 10,000 次
bootstrap。`full` 必须同时满足：

1. 五折总体 Top-5 相对 V4 至少 `+5pp`；
2. 五折 Enron Top-5 相对 V4 至少 `+5pp`；
3. 五折总体和 Enron MRR 均不下降；
4. Enron、Historical、Integer、Modified EUSES 任一 Top-5 退化不超过 `5pp`；
5. 五个结构外折至少四折 Top-5 差值非负；
6. 总体 Top-5 结构组 bootstrap 95% CI 下界严格大于 0；
7. leave-Enron-out 的 Top-5 和 MRR 均不低于 V4；
8. Historical/Integer/Modified EUSES 三个 leave-one-corpus-out 测试中至少一个 Top-5
   相对 V4达到 `+5pp`，且三者任一退化不超过 `5pp`。

Top-1、事件宏、EXAM、Info1、系数方向和四项消融只作次要解释，不补救主门失败。

## 决策

- 任一硬门失败：AETR 不成为候选，不访问保密 `240+120`，结果只说明当前监督线性
  映射仍不足；
- 全部门通过：只授权提交新的候选冻结协议、四项消融和完整公开预测；公开通过本身仍
  不是论文主模型结论；
- 只有冻结后在保密 `240+120` 一次性验证并通过预先提交的比较门，才可能晋级主模型；
- 无论结果如何，`V4-R1` 在正式晋级前保持唯一主排序器。
