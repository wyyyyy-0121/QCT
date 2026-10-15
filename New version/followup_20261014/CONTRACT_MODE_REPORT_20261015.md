# 作者合同辅助模式

本轮增加一个与工作簿自身证据分开的辅助模式。它要求合同在预测前单独提供，并绑定到工作簿 SHA-256；合同必须声明作者、来源、来源状态、表头行、有限数据行、输出列、输入角色和公式模板。允许声明按行例外或排除行。合同不从 `truth.json`、评分文件、错误注入日志或模型答案生成。

合同模式会拒绝未声明范围、重复/冲突行规则、未知角色、原始 A1 引用、隐藏或重复表头、缺少数值输入、公式不支持以及工作簿哈希不匹配。它最多提出一条候选，不修改输入；与已存在的上游建议冲突时，合同结果覆盖该单元格的输出状态。声明合同的作者身份目前不自动验证，合同模式明确标记为 `main_acceptance_eligible=false`。

## 当前证据

`tests/test_contract_mode_dev1.py` 共 16 项通过，覆盖输出列和行边界、按行例外、排除行、合同与工作簿绑定、完整预测覆盖、未知引用、隐藏/重复表头、执行失败和未验证作者身份。`development/contract_scope_smoke_dev1/` 在一个已揭示跨域样例上完成只读 smoke run；它没有被计入最终验证，也没有读取答案。

`source_discovery/index_audit_20261015/RECEIPT.json` 是新增的来源索引审计。它只读取索引页面或固定 Git 树元数据，不下载工作簿正文和错误答案。审计确认 7 个候选来源组存在可访问的工作簿链接或路径：Iowa State、Damodaran、EPA、英国政府、18F、Packt 和 Renewables。该结果仍不能证明许可范围、独立性、历史错误配对或模板家族数；最终合格来源数保持 0。

合同模式和来源索引均是前置研究证据，不能替代三类最终独立验证。模型尚未冻结，最终数据正文和答案仍不能读取。

验证命令：

```text
python -m unittest tests.test_contract_mode_dev1 -v
python scripts/run_contract_mode_dev1.py --input ... --upstream ... --contract ... --output ...
python scripts/audit_source_indexes_dev7.py
```
