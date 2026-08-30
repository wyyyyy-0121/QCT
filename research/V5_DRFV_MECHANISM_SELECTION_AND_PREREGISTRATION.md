# FormulaGuard DRFV 机制选择与预注册

日期：2026-08-31  
协议：`formulaguard_drfv_preregistration_v1`  
状态：在读取 SpreadsheetBench 工作簿内容和 SpreadsheetBench 2 数据包前冻结  
研究代号：`DRFV`（Density-Ratio Formula Verifier，不是正式版本名）

## 1. 选择结论

Gate 2 已证明，单工作簿内的离散模式、图、反事实和修复响应不能在各语料上稳定超过
`V4-R1`。CWRP 又证明，低复杂度跨工作簿角色计数不足：工作簿宏 Top-5 只有 7.81%，
显著低于 `context_frequency` 的 21.58% 和 `local_peer` 的 81.39%。因此下一条线不能
继续调已有分数，也不能把 CWRP 的测试折改作神经模型开发集。

本协议只授权一个新机制：

> 从新的无故障标签工作簿中，学习真实公式与结构保持型伪错误在局部结构上下文下的
> 条件密度比；推理时把每个已观察公式被替换的证据直接用于完整源格排名。

候选不读取输出真值、通过/失败位、故障标签、正确公式、V4 排名、单元格文字或原始
数值。V4 只作冻结比较基线。只有本协议全部门通过后，才允许为它讨论正式版本身份。

## 2. 先验工作与原创性边界

以下均是已有工作，不能作为 DRFV 的原创性主张：

- ExceLint 的相对引用指纹、区域异常和修复候选；
- CUSTODES/WARDER 的公式 AST、引用关系聚类和离群检测；
- SpreadsheetCoder 的半结构化上下文公式预测；
- HermEs 的层次化 Formulet 公式生成；
- FLAME 的公式专用 tokenizer、遮蔽预训练、17 类用户噪声和公式修复；
- LaMirage 的神经符号修复；
- 一般的噪声对比估计、替换检测和选择性预测。

允许检验的窄贡献是：**条件公式模型是否能以密度比验证器而非生成器的形式，在不知
道目标格和期望输出时给出源错误完整排名，并在罕见合法公式上比原始似然更安全。**
这只是研究假设。若完整 DRFV 不同时超过无上下文消融、同工作簿 `local_peer` 和
`V4-R1`，则新增机制没有独立价值，不能用“融合前人经验”替代失败结论。

## 3. 新数据与许可冻结

### 3.1 自监督训练、校准和内部测试

- 数据：SpreadsheetBench v1 的 912 任务归档，只读取每项 `spreadsheet_path` 下的
  `*_input.xlsx`；禁止读取 instruction、answer_position 和 `*_answer.xlsx`。
- 上游：`https://github.com/RUCKBReasoning/SpreadsheetBench`
- 固定提交：`49b73a94775fb489063f60ca1865e3a650079a79`
- 本地归档：`spreadsheetbench_912_v0.1.tar.gz`
- 归档 SHA-256：
  `9cf7228b54f1edcdd4b372eb736774adf29cb4f804c9920229bac6c154833399`
- 归档大小：95,752,357 字节；归档元数据列出 5,464 个 Excel 文件，实际输入数、
  去重数和可解析公式数只能由接收器在本协议提交后审计。
- 许可：仓库 README 声明 CC BY-SA 4.0；原始工作簿不提交 Git，不对外再分发。

这批输入此前只以归档级角色进入 parser-stress 清点，没有进入 CWRP 训练或测试。
SheetJS `nuix/` 的 303 个 CWRP 工作簿及五个已揭晓测试折全部排除。

### 3.2 独立外部测试

- 数据：SpreadsheetBench 2 的 100 个 Debugging 任务；全部保留为锁后测试，不用于
  训练、阈值、早停、扰动设计或失败诊断后的重试。
- 数据仓库：`https://huggingface.co/datasets/KAKA22/SpreadsheetBench-v2`
- 固定数据 revision：`9dea60025792fbac5928ce9f44812362dccbeecd`
- 完整数据包 LFS SHA-256：
  `17147ef9578cd57ce76c9a719d19da7821f3e5cb0d8f776c820f699fdcdb761c`
- 包大小：134,207,025 字节。
- 评测代码提交：`5c160265aa93c15b38e4034cbf1e09ab498335d9`
- 许可解释：论文正文声明数据 CC BY-SA 4.0、评测代码 MIT；Hugging Face 卡片把整库
  标成 MIT，与正文不一致。本项目按更严格的 CC BY-SA 4.0 处理数据，并保留第三方
  来源限制；不把原始工作簿提交 Git。

论文公开信息已知：321 项中有 100 项 Debugging，指令不公开错误类型或目标格，每项
含一个或多个专家注入错误，平均 21.1 张表和 656.6 个修改格。当前只读取了这些聚合
统计、公开错误 taxonomy、仓库元数据和许可，尚未下载数据包或读取任何任务实例、
输入工作簿、金标准工作簿或逐项标签。

### 3.3 WTM/FUSE 决定

Workbook Time Machine 论文把完成工作簿反向分解为创建任务，报告 WTM-Corpus 有
2,977 项任务和 8,931 条查询；它不是自然版本错误历史。到冻结时，论文 HTML 没有
项目、代码或数据链接，GitHub 标题搜索也未发现公开仓库。FUSE 原始语料同样未找到
可复算下载入口。因此二者只进入相关工作/未来数据来源，不是本协议的执行依赖。

## 4. 数据接收与泄漏控制

预注册提交后才实现接收器。接收器必须 fail closed：

1. 从 v1 归档只物化 `*_input.xlsx`，不物化 answer 文件；任务 JSON 只允许程序读取
   `id` 和 `spreadsheet_path`，不把 instruction、answer_position 或答案路径写入输出；
2. 对每个输入记录来源 ID、字节 SHA-256、工作表数、公式数、可解析公式数和拒绝原因，
   不记录文件名语义、工作表名、单元格文字、原始数值或公式常量字符串；
3. 对字节重复、精确公式结构重复和 weighted-Jaccard `>=0.80` 的近重复建立连通分量；
4. 与 Gate 2、CWRP、Enron Error、Modified EUSES、Integer、Info1 以及随后接收的
   SpreadsheetBench 2 输入做同样结构去重；重合分量只能从训练侧删除，不能删除测试；
5. SpreadsheetBench 2 接收器在候选冻结前只物化 Debugging input；golden 文件保持在
   独立封存归档中。预测锁必须记录 `gold_inputs=[]`；锁成功后才允许物化 golden；
6. 接收、拆分、训练、预测和评分输出目录不可原地覆盖；每份回执写入数据、源码、配置
   和上游 revision 哈希。

## 5. 语料门 U0

只有下列条件全部满足才训练：

- 至少 300 个非重复、可解析的 v1 input 工作簿；
- 至少 100 个结构近重复连通分量；
- 至少 100,000 个可解析公式；
- 至少 80% 工作簿的可解析公式比例不低于 50%；
- 与全部已知开发/测试语料重合的训练分量已删除；
- 敏感文字特征、原始数值特征、故障标签输入、V4 输入和保密数据输入计数均为 0。

U0 失败就停止，不改用 answer 工作簿补数量，不回收 CWRP 折，也不读取保密数据。

## 6. 固定自监督样本

### 6.1 正样本和上下文

每个工作簿最多按稳定哈希选 128 个可解析公式格。目标公式本身作为候选序列；上下文
中排除目标公式和计算值，只包含：

- 候选公式的 lexer token、相对 A1 引用、函数和运算符，最多 96 token；
- 同表 Manhattan 距离最近的 24 个公式，分别按自身地址规范化，记录截断公式 token
  和相对行列桶；
- 目标周围 `9x9` 的 `blank/constant/formula` 类型拓扑；
- 最多 8 个静态引用/被引用邻居的公式结构和距离桶；
- 目标位置桶、公式密度桶、入度和出度桶。

文字、文件名、工作表名、原始数值、格式颜色和公式缓存值全部禁止。

### 6.2 八类负样本

每个 epoch 为每个正样本按稳定种子生成两个负样本，均须通过同一个公式 parser，且
规范结构确实改变。适用操作按下列固定顺序轮转，不适用则跳过：

1. 单引用行偏移 `+1/-1`；
2. 单引用列偏移 `+1/-1`；
3. 连续区域一个端点扩张或收缩一格；
4. 相对/绝对行列锚切换；
5. 算术或比较运算符在固定同族表内替换；
6. `SUM/AVERAGE/MIN/MAX/COUNT/COUNTA` 固定同族函数替换；
7. 以局部同伴的一个相对引用替换候选中的同类型引用；
8. 在多表工作簿中把一个显式跨表引用替换为另一工作表序号。

不增加为 SpreadsheetBench 2 某个揭晓错误专门设计的操作。上下文打乱安慰剂只在
评分副本中进行，不参与训练。

## 7. 固定模型与训练

唯一候选是一个候选公式/上下文联合 Transformer encoder：

- `d_model=192`，4 层，6 heads，FFN 768，dropout 0.10；
- 最大联合序列 512 token；lexer token、segment、行列桶和依赖距离分别嵌入后相加；
- `[CLS]` 经单线性头输出 `real` 对 `corrupted` logit；该 logit 是固定噪声分布下的
  条件密度比估计，源格异常分数为其相反数；
- 不生成公式，不用候选修复反向改分，也不与 V4 融合。

结构连通分量按签名 SHA-256 排序，前 70% 为训练、随后 15% 为校准、最后 15% 为
内部测试；同一分量不可跨集合。固定随机种子 `260831`，PyTorch deterministic 模式，
batch 32，AdamW，学习率 `3e-4`，weight decay `0.01`，梯度裁剪 1.0，最多 12 epoch。
只按校准集工作簿宏 AUROC 早停，patience 2；不做网格搜索、学习率搜索、架构搜索或
多 seed 选优。

## 8. 固定内部基线、消融和门 U1

内部测试为每个目标构造一个固定负例工作簿，并在该工作簿全部可解析公式中定位被替换
格。完整模型必须同时与下列方法比较：

- 冻结 `V4-R1`；
- `local_peer`：同工作簿可平移同伴离群分；
- `formula_only`：同一网络去掉全部工作簿上下文；
- `context_shuffled`：测试时在结构组间置乱上下文；
- `random_prevalence`：等概率公式排名。

U1 必须全部通过：

1. 工作簿宏 Top-5 同时高于 V4 和 local-peer 至少 5 个百分点；
2. 八类扰动至少七类相对 V4 不为负，任何一类不得下降超过 5 个百分点；
3. 在没有精确可平移 local peer 的子集上 Top-5 至少 40%，且高于 local-peer 10pp；
4. 完整模型比 `formula_only` 至少高 3pp，比 `context_shuffled` 至少高 10pp；
5. 等频 10 桶 ECE 不超过 0.10；由校准集唯一选择的行动阈值在测试集达到 precision
   至少 75%、错误覆盖至少 30%、未扰动配对控制行动率不超过 15%；
6. 两次独立进程运行的样本、拆分和 CPU 重算预测哈希一致。

U1 第一次正式评分后禁止改变结构、token、扰动、拆分、阈值或门槛。实现错误可以修，
但原回执永久保留，修复须有最小回归测试并完整重跑。

## 9. SpreadsheetBench 2 锁后外部门 U2

U1 通过后才提交候选源码、配置、模型权重和环境冻结。随后：

1. 只接收 100 个 Debugging input，先删除与它们重合的训练分量并按原配置重训一次；
   这次去重重训是预注册步骤，不读取 gold，也不允许其他改变；
2. 对 input 独立运行 DRFV、V4、local-peer 和可运行的 ExceLint 原生区域输出；
3. 写出每个可解析公式的完整排名，生成源码、配置、权重、输入和预测 SHA-256 锁；
4. 预测锁验证 `gold_inputs=[]` 后才物化 golden 工作簿并评分；
5. gold 只机械定义同地址公式差异，禁止人工挑选“合理错误”。

主要任务只纳入：input 至少 5 个可解析公式、gold 同地址至少 1 个公式发生变化、公式
变化格占 input 可解析公式不超过 50%。新增/删除格、常量、格式、显式错误值和解析不
支持项分别报告，不计入公式源格主指标。近重复结构连通分量是统计单位。

主要指标是任务宏 `precision@5`，并同时报告 changed-formula prevalence、相对随机的
excess precision、hit@5、MRR、AP、各任务全部变化格数量和五格审查成本。U2 必须：

- 至少 50 个合格任务、30 个结构组，否则证据只算探索性且不得晋级；
- DRFV 的任务宏 precision@5 同时高于 V4 和 local-peer 至少 5pp；
- 结构组配对 bootstrap 的 DRFV-V4 precision@5 差值 95% 下界大于 0；
- hit@5 相对 V4 至少提高 5pp，MRR 不下降超过 0.02；
- 至少 80% 外部结构组的方向不与总体提升冲突；
- 用 gold 修复后的同一批工作簿按冻结行动阈值重跑，控制行动率不超过 15%；
- ExceLint 只按其原生 region-hit/审查成本报告，不把区域输出伪造成逐格 MRR。

U2 失败后禁止查看逐项结果来修改模型，也禁止把 SpreadsheetBench 2 降级为开发集。

## 10. 保密数据与正式身份

DRFV 只有 U0、U1 和 U2 全部通过，且最终候选规格、源码、配置、权重、环境和完整
公开预测锁均已提交后，才可进入保密 `/home/ayaka/code/FormulaGuard_240_120/` 的
一次性流程。此前禁止列目录、哈希或读取。用户已授权满足条件后由 Codex 直接执行，
无需再次确认；此授权不允许提前访问或把保密数据用于调参。

保密 `240+120` 通过也不自动证明自然错误普遍泛化。SpreadsheetBench 2 和保密数据
若为专家注入，只能支持独立未见工作簿/模板上的注入错误结论。正式 `V5-R1` 还要求
保密集达到预注册提升、控制安全、完整性和统计门；在那之前一律使用 `DRFV` 研究代号。

## 11. 失败政策与论文写法

任一门失败都保留权重、预测、哈希、环境、逐基线结果和失败原因并停止本线。不得：

- 在同一内部测试或 SpreadsheetBench 2 上换 Transformer、增加特征或连续调参；
- 把公式生成/修复准确率换算成源错误定位优势；
- 声称超过 FLAME、SpreadsheetCoder、HermEs 或 CUSTODES，除非获得共同任务实现；
- 用总体平均掩盖某一语料、扰动类型或控制安全下降；
- 把一次应用新颖性写成基础模型或噪声对比学习首创。

只有完整门通过时，允许的贡献表述是：`a context-conditioned density-ratio verifier
turns self-supervised formula corruption discrimination into oracle-free source-cell ranking,
with gains over V4 and local-peer baselines on locked independent workbooks`。实际论文措辞仍
必须受最终共同任务证据限制。
