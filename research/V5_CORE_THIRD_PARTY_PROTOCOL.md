# FormulaGuard V5-Core 第三方600例交接协议

第三方数据必须在仓库 `D:\code\QCT` 之外准备。出题人可以使用自建或合法公开
模板，但不得查看V5-Core开发、验证或历史错误标签，也不得根据模型结果删题。
项目内置数据生成命令会明确拒绝生成最终600例，防止把已知模板的合成数据冒充
第三方独立验证。

输入目录至少包含：

```text
instances.jsonl
evaluation_labels.jsonl
third_party_provenance.json
workbooks or mutants/*.xlsx
originals/*.xlsx
```

`instances.jsonl`的每行包含`instance_id`、`mutant_workbook`、`template_family`、
`topology_id`、`regime`和`ambiguity`。`evaluation_labels.jsonl`只由出题人保管，
每行包含`instance_id`、`original_workbook`、`source_cell`、`correct_formula`、
`mutated_formula`、`mutation_type`、`sink_cell`和`actual_depth`。

`third_party_provenance.json`使用以下声明；`preparer_role`可以写“指导老师”或
“独立同学”，不要求姓名：

```json
{
  "preparer_role": "independent teacher or student",
  "prepared_by_independent_person": true,
  "project_localizer_results_not_seen": true,
  "secret_seed_withheld": true,
  "templates_unseen_by_project": true,
  "all_valid_cases_retained": true
}
```

出题人在自己的目录运行：

```bat
python D:\code\QCT\scripts\prepare_v5_core_third_party_pack.py ^
  --input D:\FormulaGuard_V5_ThirdParty\source_600 ^
  --output D:\FormulaGuard_V5_ThirdParty
```

打包器会重新打开全部原表和错误表，要求六类错误各100例、每例只改变一个源公式、
无显式计算错误、源公式仍返回数值、正确/错误公式与工作簿一致、声明下游确实改变，
并复算传播深度。它还会检查120例人工/半人工、100例跨表或长链、100例非简单
相邻平移和60例合法特殊结构门槛。

冻结前只交付`third_party_precommit.json`中的PUBLIC、SECRET、labels及设计账本
SHA-256，不交付工作簿。`v5-core-lock`推送后交付PUBLIC包；预测锁成功后才交付
SECRET包。秘密包、原表、标签和秘密种子不得提交Git。
