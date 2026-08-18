# FormulaGuard 文献矩阵

## A. 直接相关方法

| 编号 | 工作 | 需要的真值/输入 | 主要思想 | 本项目怎样比较或区分 |
|---|---|---|---|---|
| L01 | Abraham & Erwig, GoalDebug, ICSE 2007 | 用户给出期望输出 | 由目标值生成并排序公式修改建议 | 作为“有输出真值修复”代表；FormulaGuard 不读取期望输出 |
| L02 | Abraham & Erwig, Spreadsheet Debugging, 2008 | 调试交互/数据流 | 通过数据依赖和影响关系辅助定位 | 依赖图是基础，不作为本项目首创 |
| L03 | Hofer et al., FASE 2013 | 测试通过/失败 | SFL、动态切片、约束调试实证比较 | 实现 truth-assisted SFL 参考，与无真值组分开 |
| L04 | Hofer et al., FaultySheet Detective, 2014 | 测试结果与气味 | 将公式气味与故障定位结合 | 对比静态模式异常和测试信息 |
| L05 | MUSSCO, 2015 | 错误与变异候选 | 基于变异生成修复候选 | 借鉴小编辑候选，不复用其评分结论 |
| L06 | Barowy et al., ExceLint, OOPSLA 2018 | 无输出真值 | 信息论与空间区域中的惊异公式 | 主要无真值强基线；FormulaGuard增加根因传播和干预 |
| L07 | Metric-based Fault Prediction, 2019 | 历史/静态度量 | 预测单元格或工作簿故障倾向 | 与具体实例根因排序任务不同 |
| L08 | WARDER, 2020 | 无输出真值 | 基于有效性的单元格聚类细化，检测缺失/不一致公式 | 实现透明的 WARDER-like 公式族基线 |
| L09 | LaMirage, 2022 | 公式上下文 | 神经符号低代码公式修复 | 作为修复相关工作；非主复现对象 |
| L10 | FLAME, 2023 | 大规模公式语料 | 预训练模型生成电子表格公式 | 作为学习式修复背景，不作为CPU主算法 |
| L11 | FoRepBench, 2025 | 表格上下文、错误/正确公式、用户意图 | 上下文公式修复基准 | 仅作候选修复补充，错误多为显式运行时错误 |
| L12 | Yang et al., SEDMR, IST 2026 | 输入扰动与蜕变关系 | 七类蜕变关系检测电子表格错误 | 实现 behavior/SEDMR-like 信号；FormulaGuard输出源错误排名 |

## B. 数据与实验方法

| 编号 | 工作/语料 | 可借鉴内容 |
|---|---|---|
| D01 | Enron Error Corpus | 36 个真实错误及错误单元格 properties 标签，用于外部验证 |
| D02 | Modified EUSES | 184 个基础表、576 个故障版本；适合故障定位与SFL评测 |
| D03 | EUSES Spreadsheet Corpus | 真实来源工作簿与高度复制公式结构，适合公式族方法 |
| D04 | SpreadsheetBench | 真实复杂工作簿压力测试，不作为源错误准确率真值 |
| D05 | FoRepBench | 合成生成后仍需要执行验证和人工抽查，支持本项目的数据审计设计 |

## C. 当前采用的正式引用条目

1. Abraham, R.; Erwig, M. GoalDebug: A Spreadsheet Debugger for End Users. ICSE 2007, pp. 251-260. DOI: 10.1109/ICSE.2007.39. https://web.engr.oregonstate.edu/~erwig/papers/GoalDebug_ICSE07.pdf
2. Abraham, R.; Erwig, M. Spreadsheet Debugging. 2008. https://arxiv.org/abs/0802.3479
3. Hofer, B.; Riboira, A.; Wotawa, F.; Abreu, R.; Getzner, E. On the Empirical Evaluation of Fault Localization Techniques for Spreadsheets. FASE 2013, pp. 68-82. DOI: 10.1007/978-3-642-37057-1_6.
4. Hofer, B. et al. The FaultySheet Detective: When Smells Meet Fault Localization. 2014. https://gzoltar.com/pub/18.pdf
5. MUSSCO: A Mutation-Based Spreadsheet Formula Repair Approach. 2015. https://dl.ifip.org/IFIP-LNCS-9447/hal-01470160
6. Barowy, D. W.; Berger, E. D.; Zorn, B. G. ExceLint: Automatically Finding Spreadsheet Formula Errors. OOPSLA 2018. https://www.microsoft.com/en-us/research/publication/excelint-automatically-finding-spreadsheet-formula-errors/
7. WARDER: Towards Effective Spreadsheet Defect Detection by Validity-Based Cell Cluster Refinements. Journal of Systems and Software, 2020. https://www.sciencedirect.com/science/article/pii/S0164121220300935
8. Bavishi, R. et al. LaMirage: Neurosymbolic Repair for Low-Code Formula Languages. 2022. https://www.microsoft.com/en-us/research/publication/neurosymbolic-repair-for-low-code-formula-languages/
9. FLAME: A Small Language Model for Spreadsheet Formulas. 2023. https://arxiv.org/abs/2301.13779
10. Benchmark Dataset Generation and Evaluation for Excel Formula Repair with LLMs (FoRepBench). KDD-Eval 2025. https://kdd-eval-workshop.github.io/genai-evaluation-kdd2025/assets/papers/Submission%2033.pdf
11. Yang, B. et al. SEDMR: A Spreadsheet Error Detection Approach Based on Metamorphic Testing. Information and Software Technology 194 (2026), 108074. DOI: 10.1016/j.infsof.2026.108074.
12. Enron Error Corpus. https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/enron-error-corpus/
13. Corpora Overview and Modified EUSES. https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/corpora-overview/
14. Spreadsheet corpora comparison. https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/corpora-comparison/
15. ExceLint source code. https://github.com/ExceLint/ExceLint
16. SpreadsheetBench. https://spreadsheetbench.github.io/

## D. 引用纪律

- 论文中的方法事实必须回到原论文核对，不引用搜索摘要或 AI 转述。
- 没有成功运行原作者代码时，实验名称必须写成 `-like` 或 `reimplementation`。
- 引用公开数据时记录下载日期、版本、许可和文件哈希。
- 任何实验数字只能引用本项目 `results/raw/*.csv` 生成的表，不从计划书目标值复制。
