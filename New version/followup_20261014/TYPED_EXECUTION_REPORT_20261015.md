# Typed execution compatibility audit

本轮在已排除最终验证的 `dgorissen/pycel` 固定 14 个工作簿上加入保守的 typed execution adapter。该适配器把 OOXML `t="e"` 单元格保存为 `ExcelError`，保留同样拼写的普通文本，传播引用/运算/聚合中的错误，并让 `IF` 只计算实际选中的分支。未支持语法记录失败，不猜测数值，也不把执行结果当作业务正确公式。

适配器单元测试 5 项通过；全套研究测试 43 项通过。逐格执行审计读取 5,117 个原始公式声明，原模型加载 5,117 个公式单元格。typed adapter 与已锁定 LibreOffice 结果有 967 项一致；另有 2,576 项 typed adapter 报错而 LibreOffice 返回数值、379 项返回文本、227 项返回布尔值，636 项错误代码不同。原模型与 typed adapter 有 929 项一致，3,670 项错误表示不同。这些差异只说明公式执行语义覆盖仍有限，不能说明任一结果符合业务意图。

这 14 个工作簿没有错误位置与正确公式标签，来源继续永久排除最终验证；本轮不报告精确率或覆盖率，也不生成修复建议。全部输入哈希、适配器输出、逐格比较和独立复核保存在 `development/typed_execution_dev1/`，复核结果为 `qa/TYPED_EXECUTION_DEV1_VERIFICATION_20261015.json`。
