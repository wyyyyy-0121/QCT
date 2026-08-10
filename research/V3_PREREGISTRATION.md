# FormulaGuard-v3 预注册研究方案

版本日期：2026-08-11  
研究名称：FormulaGuard-v3：结构自适应反事实责任定位（Structure-Adaptive Counterfactual Responsibility）

## 1. 研究定位

v2 已在冻结提交 `672a62523ff9c0a36e2b9712bf7a9be3746c8f61` 上完成正式实验。v3 是独立研究周期，不覆盖或重新解释 v2 结果；其开发、验证和测试数据、输出目录、冻结配置与 Git 标签均独立。

v2 的关键未解决问题是：完整模型的 MRR 低于移除局部图异常项的消融模型，说明固定图先验会在部分拓扑中损害排序。v3 研究如何根据局部公式结构的可靠度自适应使用图证据，并通过反事实干预区分源错误与受影响下游公式。

## 2. 预注册假设

- H1：结构自适应先验能减少不可靠局部图模式导致的误排序。
- H2：奖励约束恢复、惩罚干预副作用的净反事实增益能改善源错误定位。
- H3：路径责任能让源错误早于其传播后代，同时不能单独制造高分。
- H4：证据强度阈值能降低干净工作簿误报，而不明显损害定位率。

## 3. 固定方法

### 3.1 局部结构可靠度

对单元格 `v`：

- `peer_coverage=min(1,|peers(v)|/4)`；
- `copy_consistency=同行公式指纹众数频率`；
- `rho=peer_coverage*copy_consistency`，无同行时为 0。

自适应权重固定为 `w_formula=0.45`、`w_graph=0.20*rho`、`w_behavior=0.55-0.20*rho`，三项之和恒为 1。

### 3.2 净反事实增益

对候选修复 `c` 和能量分量 `j`：

- `gain_j=max(0,E0_j-Ec_j)/max(E0_j,eps)`；
- `harm_j=max(0,Ec_j-E0_j)/max(E0_j,eps)`。

`raw_gain=0.20*g_formula+0.15*rho*g_graph+0.25*g_behavior+0.40*g_constraint`

副作用使用相同分量权重；`net_gain=max(0,raw_gain-0.50*side_effect)`。

### 3.3 路径责任

- `influence=log(1+后代数)/log(1+最大后代数)`；
- 表名含 `check`、`audit`、`control` 或 `validation` 的公式为可见检查节点；
- `structural_path=0.60*influence+0.40*normalized_check_reach`；
- `downstream_recovery` 为候选干预后，源及其可达公式节点上异常能量的归一化恢复比例；
- `path_responsibility=structural_path*downstream_recovery`。

不使用错误标签、正确公式或标注汇点。递推块首个种子公式保留 0.25 边界折减。

### 3.4 最终分数

`P*=(w_f*A_f+w_g*A_g+w_b*A_b)*boundary_factor`

`CAR=0.20*P*+0.60*net_gain+0.10*net_gain*path_responsibility+0.10*net_gain*Q`

其中 `Q` 为候选质量，`evidence_strength=net_gain*Q`。路径和候选质量只有在净改善为正时加分，路径责任不得改变无正反事实证据单元格的先验排序。

预数据修订记录（2026-08-11）：在未生成或查看任何 v3 数据前，工程接口探针表明旧写法可能让高下游数量本身抬高先验，这与 H3 冲突。因此删除先验中的路径乘数，并要求结构路径与实际下游恢复相乘后才能获得路径奖励；最终 CAR 权重不变。该修订发生在 v3 数据生成与 quick 之前，不计为 quick 后算法修改。

## 4. 数据隔离与指标

- 开发族只用于实现；验证族只用于 quick 与唯一一次有记录的冻结前修订；测试族冻结前禁止查看结果。
- v2 full 和 Enron 均不得用于 v3 调参。
- 新增 Source-before-descendants、Source-first-in-causal-cone、Path coverage、Repair safety 与 Clean alarm rate。
- 差异使用工作簿实例配对 bootstrap 95% 置信区间。

## 5. 冻结门槛与停止规则

quick 要求：有效率不低于 95%，Coverage@15 不低于 90%，错误召回不低于 80%，干净表误报不高于 20%，v3 MRR 不低于同批数据上的 v2，且任一 v3 消融不得高出完整模型 0.02 以上。通过后生成独立 `frozen_config_v3.json`。

v3 只有在新测试集满足以下任一条件时成为论文主模型：

1. v3-v2 配对 MRR 差值为正且 95% 置信区间下界大于 0；或
2. 干净表误报率至少降低 5 个百分点，同时 MRR 下降不超过 0.01、Top-5 不下降。

此外至少一个源责任指标必须提高，Enron 不得实质退化。full 产生后不得再改权重、阈值、候选数量或核心公式；纯工程故障必须记录并完整重跑。

## 6. 唯一一次 quick 后修订（2026-08-11）

第一次 quick 在提交 `4e79825e4385b31645d6145703b0bc9c753fd4f0` 上完成，48/48 实例有效并通过原冻结门槛，但暴露出一个确定的截断缺陷：`cashflow_lattice_v1` 的两例浅层错误均排第 51，而实现只对先验 Top-50 做反事实干预。两例正确修复都已位于 Candidate Top-15；将 v3 干预覆盖提高到 100 后，两例均升至第 1，且正确修复一致。另有四例路径覆盖失败，原因是解释输出只序列化前 10 个可达终点，标注汇点虽可达却被截断。

依据“quick 只允许一次有记录的算法修订”，本次也是唯一一次 quick 后修订：

1. v3 对公式数不超过 100 的工作簿执行全公式反事实干预；更大工作簿仍按先验进行有界筛选；
2. 路径解释输出全部可达的可见检查节点和结构汇点，不再只保留前 10 条。

本次不修改 CAR 权重、候选生成规则、Candidate Top-15、报警目标或数据生成器；未读取 v3 full 测试结果或 Enron 结果。原 quick 证据保存为 `results/v3_quick_pre_revision`，修订后必须完整重跑 quick 并重新冻结，旧 `frozen_config_v3.json` 不得用于 full。
