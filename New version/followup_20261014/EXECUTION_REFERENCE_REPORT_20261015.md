# 独立执行语义对照报告

这轮实验只检查公式读取和求值语义，使用已经排除出最终验证的 `dgorissen/pycel` 固定提交中的14个公开样例。它不增加来源或模板家族，也不提供自然错误标签。

## 方法

在登记执行方法后，全部样例由系统 LibreOffice 26.2.6.3 以独立用户配置打开，设置只读选项并调用 `calculateAll`。子进程为每个工作簿单独启动，超时上限120秒；结果只写到新的审计目录，不保存输入工作簿。原始OOXML中的每个`<f>`声明都先独立记录，因此数组结果跟随单元格、共享公式和读取器没有载入的声明不会从分母中消失。

每个结果保留错误、缺失、数值、文本和布尔类型。数值用相对和绝对误差`1e-8`比较，布尔值不与0/1数值合并，文本逐字比较。原模型结果和原始缓存只作执行对照；没有任何业务正确公式或修复答案被读取。

## 结果

| 对照项 | 数量 |
|---|---:|
| 原始公式声明 | 5,117 |
| 原模型与独立引擎均为相同可比结果 | 929 |
| 原模型报错、独立引擎返回非错误结果 | 3,222 |
| 两边均报错但错误表示不同 | 896 |
| 原始缓存与独立结果数值/文本不一致 | 94 |
| 原始缓存与独立错误表示不同 | 219 |
| 原模型未载入但独立记录的声明 | 63 |

3,222项不能直接称作错误修复机会。公开样例包含不支持函数、数组/共享公式、日期基准、插件函数、故意的错误输入和错误传播。例如：

- `NPV`样例的参数同时含文本和布尔值，工具的参数强制转换规则不同；
- `YEARFRAC`样例使用加载项形式的函数名，独立引擎和原模型对其支持方式不同；
- `Logical`样例有`IF(1;A26)`，输入是错误字符串时，原模型会把它作为文本返回，而独立引擎保留Excel错误语义。

因此，原模型报错与独立引擎有结果，只能说明“存在待研究的执行支持差异”。原始缓存也可能来自旧版本或不同计算引擎；错误字符串不同不必然表示业务语义不同。至少7项错误传播差异已经被定位，但尚未形成可用于修复选择的业务标签。

## 复现和限制

运行入口为 `scripts/run_public_execution_audit.py`：

```text
python scripts/run_public_execution_audit.py smoke
python scripts/run_public_execution_audit.py register
python scripts/run_public_execution_audit.py execute
python scripts/run_public_execution_audit.py analyze
python scripts/run_public_execution_audit.py verify
python scripts/verify_execution_reference.py
```

小型集成检查覆盖数值、布尔、文本、空文本、除零错误和数组跟随单元格，并确认输入哈希不变。14个样例的执行耗时为5分36.71秒，用户态CPU 55.54秒，系统态CPU 128秒，峰值RSS 183,388 KiB；单工作簿耗时和逐格结果保存在`development/execution_reference_dev1/`。独立核查程序重新读取原始XML、重新读取原模型、重新计算每个比较关系并验证全部锁：`qa/EXECUTION_REFERENCE_INDEPENDENT_VERIFICATION_20261015.json`。

该实验没有精确率、覆盖率或最终验证资格。任何后续执行支持改进都必须在新的开发数据上登记、保留复杂公式和错误值反例，并在模型冻结后另行获取最终验证集。
