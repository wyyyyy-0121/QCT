# FormulaGuard 第三方代码与数据说明

## 代码依赖

- Python 核心定位、评价和统计代码只使用 Python 标准库。
- 单元测试使用 `pytest`，遵循其项目许可证；本仓库不复制 pytest 源码。
- `.xlsx` 生成、渲染和结果工作簿导出使用 Codex Desktop 环境提供的 `@oai/artifact-tool`；本仓库不复制或重新分发该工具源码。
- 用户提供的参考论文只用于章节组织参考，不随项目公开分发。

## 外部数据

- PropagationBench-Synthetic 是本项目代码生成的合成数据，随本项目 MIT 代码许可证发布时应单独标注其合成性质。
- Enron Error Corpus、Modified EUSES、FoRepBench 和 SpreadsheetBench 均由各自作者或机构发布，不受本项目 MIT 许可证覆盖。
- 在确认具体许可和再分发条件前，不把第三方工作簿提交到公开仓库；只提交下载说明、文件哈希和排除清单。

## 思想级基线

`excelint_like`、`warder_like`、`behavior` 等名称表示基于论文思想的透明简化复现，不是原作者官方代码，也不应在论文或答辩中表述为完整复现。

具体论文和数据链接见 `research/LITERATURE_MATRIX.md` 与 `research/DATA_SOURCES.md`。

