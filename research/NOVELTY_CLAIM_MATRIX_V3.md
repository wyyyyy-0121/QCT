# FormulaGuard v3 创新边界与相关工作矩阵

本文件只定义可以被原论文支持的差异，不用“别人没做过”作为创新证明。
所有 `-like` 基线均为本项目的思想级近似实现。

| 方法 | 主要输入证据 | 是否依赖错误输出/测试 | 主要目标 | 与 FormulaGuard 的重叠 | 本项目仍可主张的差异 |
|---|---|---:|---|---|---|
| ExceLint | 公式位置、相对引用和矩形区域 | 否 | 找到破坏局部矩形规律的惊讶公式 | 都使用局部公式规律和无真值检测 | FormulaGuard 把局部异常只作为先验，并进一步尝试候选替换及下游恢复；不能声称公式聚类首创 |
| Spreadsheet SFL / SENDYS | 输出单元格的正确/错误标记、依赖锥 | 是 | 对可能导致已知错误输出的单元格排序 | 都利用数据依赖图定位根因 | FormulaGuard 的问题设置不提供错误输出标记；SFL-output-oracle 只能作辅助参照 |
| WARDER | 公式单元格聚类与 validity properties | 否 | 改进表格缺陷检测 | 都利用公式族/局部有效性 | FormulaGuard 的独特部分应限定为候选修复干预与后代区域恢复，不是聚类本身 |
| CACheck | cell arrays、结构和修复规则 | 否 | 检测并修复异常 cell arrays | 都会给出修复候选 | FormulaGuard 关注“一个源错误传播出多个症状”的排序，不宣称修复规则首创 |
| SEDMR | 七类值与结构 metamorphic relations | 否 | 用变形关系投票检测错误 | 都通过改变/关系检验替代外部真值 | FormulaGuard 干预的是候选公式，并评价工作簿异常能量和依赖后代恢复；必须承认两者在无真值关系检验上有概念重叠 |
| FormulaGuard v3 | 工作簿、公式、依赖图和候选小修复 | 否 | 静默公式错误的源排序、修复建议和路径解释 | 综合公式模式、依赖和反事实检验 | 最窄且可辩护的创新是“候选修复支持下的下游反事实诊断责任排序”及其可证伪证据链 |

## 关键原文依据

### ExceLint

Microsoft Research 页面将 ExceLint 描述为利用电子表格矩形特征的静态
分析，并以信息论方法寻找破坏附近矩形区域的“surprising”公式：

https://www.microsoft.com/en-us/research/publication/excelint-automatically-finding-spreadsheet-formula-errors/

### Spreadsheet SFL

Hofer 等定义的 spreadsheet debugging 以 failing test case 为前提，并用
输出单元格依赖锥代替程序覆盖；论文还明确指出这些方法定位可能错误的
单元格，但不建议如何修改：

https://gzoltar.com/pub/14.pdf

### WARDER

WARDER 的题目和方法核心是通过 validity properties 改进 cell clustering
以进行 spreadsheet defect detection：

https://cs.nju.edu.cn/_upload/tpl/01/55/341/template341/1_publications/19/QRS19.pdf

### SEDMR

SEDMR 使用七种针对公式单元格与引用单元格的 metamorphic relations，
通过关系级检测和投票聚合进行错误检测；它已经覆盖 Enron 和 EUSES：

https://www.sciencedirect.com/science/article/pii/S0950584926000637

## 答辩时的创新表述

推荐：

> 现有无真值方法多把局部结构异常直接作为错误证据，依赖测试的方法又
> 需要用户先指出错误输出。FormulaGuard 尝试处在两者之间：先生成一个
> 可解释的小修复，再把该修复是否降低内部异常、是否恢复其依赖后代作为
> 源责任证据。我们的贡献不是发明依赖图或反事实，而是定义并审计这种
> 无输出标签的候选干预排序任务。

必须同时补充：

> 真实 Enron 试点显示，内部异常不一定为自然错误提供足够信号；因此系统
> 需要保留低证据/弃权状态，合成满分不能视为现实准确率。

## 不能使用的宣传语

- “首个无真值电子表格错误检测方法”；
- “首次把因果推断用于表格”；
- “超越 ExceLint、WARDER 和 SEDMR 原工具”；
- “真实表格100%准确”；
- “每个组件都被消融证明有效”。
