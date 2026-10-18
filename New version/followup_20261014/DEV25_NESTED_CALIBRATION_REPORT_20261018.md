# dev25：真正嵌套来源校准无新增修复，不采用

10个三来源内层模型已实际训练，852份内层案例预测先锁定；再拟合5个来源隔离校准器，对213例保存外层预测，锁定后另进程评分。固定校准规则输出0条建议，没有提高覆盖。主候选继续使用dev11，独立三类双90%目标未完成。

## 同一开发总体的结果

|模式|建议|正确|错误|未知|精确率下界|正确修复覆盖|
|---|---:|---:|---:|---:|---:|---:|
|dev11主候选|14,213|14,184|29|0|99.7960%|78.4817%|
|校准单独|0|0|0|0|N/A|0%|
|dev11＋校准|14,213|14,184|29|0|99.7960%|78.4817%|
|原始相对排序器单独|78|31|47|0|39.7436%|0.1715%|
|dev11＋原始相对排序器|14,291|14,215|76|0|99.4682%|78.6532%|

所有覆盖分母均为18,073个已标错误；unknown仍计建议分母，零建议精确率为N/A。原始相对排序器和dev24的逐例输出完全一致，校准移除了其全部78条建议，包括47条错误与31条正确。没有根据本轮外层答案放宽阈值、改变权重或重训。

作者合成部分有17,876个错误，dev11正确14,184个；四个公开开发来源有197个错误，dev11与校准均没有正确修复。因此总体78.48%覆盖主要来自作者合成，不能作为公开文件泛化表现。原始相对排序器在公开部分31/78正确、覆盖31/197；这是已否决实验臂的开发诊断。

## 固定设计和阶段隔离

完整预登记为`NESTED_CALIBRATION_DEV25_PREREGISTRATION_20261018.md`。外层来源A完全排除，对内层验证来源B，仅用其他三个来源训练；无序{A,B}共享模型，共10次新训练。每个模型预测两个排除来源，合计852份案例预测。A的校准只取对应模型对B的结果，不使用A的结果。外层排序器复用已锁dev24五个相对模型。

保持356维公式特征、712维相对表示、原配对取样、HGB100轮参数及seed1618。校准对象是通过原始0.05差距和固定语法/可见性/单位门的首位候选，拟合前不应用原始0.90阈值。校准目标用旧dev18成功修复定义；已知清洁改写为0，即使数值等价；unknown排除拟合并记录。来源/家族/case均衡权重，非递减加权isotonic，固定0.90输出门槛，范围外不外推，候选不递补。

内层训练进程只读当前三来源训练标签，内层预测锁定后校准进程只读当前四来源修复标签。学习进程不读取作者状态、外层答案、旧dev24概率/预测/评分。预检禁止标签正文哈希。全部外层输出锁定后才在独立评分进程读取完整旧答案。两个预测锁均保存源码、文件SHA及访问记录。

## 为什么没有建议

|已标错误归因|数量|
|---|---:|
|dev11已正确修复|14,184|
|首位正确但校准值低于0.90|3,113|
|首位正确但原始候选差距不足0.05|456|
|首位错误或未知|288|
|没有eligible候选|28|
|首位正确但校准范围外/不可用|4|
|合计|18,073|

五折均实际拟合成功。18F和Packt的训练校准曲线最大值分别为0.873725、0.263556，无法达到固定门槛；其他三折曲线虽达到1，外层首位候选经固定门和支持域检查后仍无输出。不能据此将“校准值不可用”归因为没有训练校准器。

本次否定的是这套表示、来源平衡、首位选择及一维校准组合。它不能证明所有校准方法无效，也不能将3,113个低校准值正确候选直接转为下一版放宽依据。此轮已揭示外层结果继续属于开发证据。

## 验证和资源

259项研究测试、2项独立PAVA测试通过。独立训练审计重建10个折的来源排除、配对和权重并核对运行摘要；独立校准审计重建852份内层首位选择、旧修复标签、权重及单调分段，并检查213份外层曲线应用和输出决定。全部852份内层与213份外层案例的概率、首位和建议另进程重放一致，7,455项逐例整数计数及来源/家族/场景汇总一致，原始dev24输出与历史锁核验通过。最终检查入口为`qa/verify_nested_dev25_checkpoint.py`，凭证为`qa/NESTED_CALIBRATION_DEV25_VERIFICATION_20261018.json`。

内层wall1,174.66秒、CPU3,228.29秒，峰值11,580,368 KiB（约11.04 GiB）；命令`time -v`耗时19:35.91，退出0。外层校准及预测wall62.41秒、CPU87.19秒，峰值2,089,568 KiB。OMP4/OpenBLAS1，GPU未用。Python3.11.16、NumPy1.26.4、scikit-learn1.9.0、joblib1.5.3。已完成一次全内层训练和保存模型重放，未声称10次重新训练也已重复复现。

训练标签拼接副本不重复上传，`qa/rebuild_nested_training_dev25.py`可由已提交逐案例选项精确重建；已有pair_01独立重建SHA匹配，其余折内容/权重由独立作者审计核对。已有实验目录拒绝覆盖，完整重跑需隔离副本并保留同一研究根路径。

```bash
/home/ayaka/hybridguard/.venv/bin/python qa/rebuild_nested_training_dev25.py
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 /home/ayaka/hybridguard/.venv/bin/python scripts/run_nested_calibration_dev25.py inner
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 /home/ayaka/hybridguard/.venv/bin/python scripts/run_nested_calibration_dev25.py outer
/home/ayaka/hybridguard/.venv/bin/python scripts/run_nested_calibration_dev25.py score
/home/ayaka/hybridguard/.venv/bin/python qa/audit_nested_training_dev25.py --check-runtime
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 /home/ayaka/hybridguard/.venv/bin/python scripts/run_nested_calibration_dev25.py replay_inner
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 /home/ayaka/hybridguard/.venv/bin/python scripts/run_nested_calibration_dev25.py replay_outer
/home/ayaka/hybridguard/.venv/bin/python qa/audit_nested_calibration_dev25.py
/home/ayaka/hybridguard/.venv/bin/python qa/audit_nested_results_dev25.py
/home/ayaka/hybridguard/.venv/bin/python qa/diagnose_nested_calibration_dev25.py
/home/ayaka/hybridguard/.venv/bin/python qa/verify_nested_dev25_checkpoint.py
```

## 下一步

优先补跨领域业务依据和可靠自然错误修订配对，停止在这批已揭示样本上连续追加分数门槛实验。当前公共开发来源修复缺口很大，下一次模型改动必须说明新增可见业务信息如何区分正确公式与合法例外，并用独立来源开发对照检验；不能只用合成大样本合并分数支持采用。

本轮资料检索找到5个历史仓库的7个同路径工作簿blob变化，已固定前后提交及Git树，但尚未取得可靠逐格自然真值；同一表的ods/xlsx不能算两个家族。详情见`source_discovery/HISTORICAL_NATURAL_FIX_CANDIDATES_DEV25_20261018.md`。最终合格来源/家族仍为0，至少6新来源、15家族、三类分别双90%保持原验收条件。原模型0.3.0和`/home/ayaka/code`保留，目标active。
