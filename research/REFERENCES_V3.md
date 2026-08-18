# FormulaGuard v3 核验后参考文献（正文顺序编码）

本表是正文引用的唯一来源。链接用于提交前复核，不要求读者通过链接获得
论文全文；正文采用 `[n]` 顺序编码。`访问日期` 均为 2026-08-18。

[1] R. Abraham and M. Erwig. “GoalDebug: A Spreadsheet Debugger for End
Users.” *Proceedings of the 29th International Conference on Software
Engineering (ICSE)*, 2007, pp. 251–260. doi:10.1109/ICSE.2007.39.
[官方论文页](https://web.engr.oregonstate.edu/~erwig/GoalDebug/)

[2] B. Hofer, A. Riboira, F. Wotawa, R. Abreu, and E. Getzner. “On the
Empirical Evaluation of Fault Localization Techniques for Spreadsheets.”
*Fundamental Approaches to Software Engineering (FASE 2013)*, LNCS 7793,
2013, pp. 68–82. doi:10.1007/978-3-642-37057-1_6.
[机构记录](https://researchportal.ulisboa.pt/en/publications/on-the-empirical-evaluation-of-fault-localization-techniques-for-/)

[3] D. W. Barowy, E. D. Berger, and B. G. Zorn. “ExceLint: Automatically
Finding Spreadsheet Formula Errors.” *Proceedings of the ACM on Programming
Languages*, 2(OOPSLA), Article 148, 2018. doi:10.1145/3276518.
[作者/机构论文页](https://www.microsoft.com/en-us/research/publication/excelint-automatically-finding-spreadsheet-formula-errors/)

[4] Y. Huang, C. Xu, Y. Jiang, H. Wang, and D. Li. “WARDER: Towards
Effective Spreadsheet Defect Detection by Validity-Based Cell Cluster
Refinements.” *Journal of Systems and Software*, 167, 110615, 2020.
doi:10.1016/j.jss.2020.110615.
[书目记录](https://dblp.org/rec/journals/jss/HuangXJWL20)

[5] B. Yang et al. “SEDMR: A Spreadsheet Error Detection Approach Based
on Metamorphic Testing.” *Information and Software Technology*, 194, 108074,
2026. doi:10.1016/j.infsof.2026.108074.
[出版社记录](https://www.sciencedirect.com/science/article/pii/S0950584926000637)

[6] T. Schmitz and D. Jannach. *Enron Error Corpus*. Spreadsheet Research
Group, Graz University of Technology. 官方数据页说明该语料含 36 个错误，并
为每份表格提供标记错误单元格的 properties 文件。访问日期：2026-08-18。
[官方数据页](https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/enron-error-corpus/)

[7] F. Hermans and E. Murphy-Hill. “Enron’s Spreadsheets and Related
Emails: A Dataset and Analysis.” *Proceedings of the 37th International
Conference on Software Engineering, Volume 2*, 2015, pp. 7–16.

## 引用使用限制

- `[3]` 只支持 ExceLint 的局部结构/信息论异常检测描述，不支持把本项目
  `excelint_like` 称为原始 ExceLint 的可复现实验。
- `[2]` 只支持“测试谱、动态切片和约束调试需要测试信息”的分类背景；本项目
  的 `sfl_oracle` 是有真值辅助参照，不属于无真值主比较。
- `[4]` 支持“有效性驱动的单元格簇细化”背景；`warder_like` 为透明思想级
  近似，不能拿来声称复现 WARDER 的精确数字。
- `[5]` 支持“输入变换/蜕变关系检测”背景；FormulaGuard 的候选公式替换与
  SEDMR 的输入蜕变测试不同，二者不能相互替代或直接比较原始论文结果。
- `[6]` 支持官方语料的事件数与标签文件存在性；本项目的 30 个可评事件、
  10/20 划分和排除原因只由项目内 audit 文件支持。
