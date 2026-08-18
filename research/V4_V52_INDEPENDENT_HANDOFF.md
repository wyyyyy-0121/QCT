# V4 / V5.2 独立验证出题人交接说明

## 出题人需要交付但暂不交给模型开发者的内容

准备 15 个互不重复的 `.xlsx`，每个只含一个主要静默公式错误。六类错误至少各 2 例；额外
3 例覆盖跨表、长传播链或合理例外公式；至少 8 例不能只是相邻引用加一/减一。原始正确工作簿、
错误位置、正确公式和制作说明均保存在项目目录外。

公开文件放入：

```text
D:\code\QCT\data\v4_v52_blind\public\workbooks\
D:\code\QCT\data\v4_v52_blind\public\manifest.csv
```

私密答案放入：

```text
D:\FormulaGuard_Blind_Labels\v4_v52_labels.csv
D:\FormulaGuard_Blind_Labels\v4_v52_exceptions.csv
```

标签表头：

```csv
instance_id,source_cell,error_type,correct_formula,source_origin,notes
```

若一个事件有多个真实源公式，增加 `source_cells` 列并用分号分隔；`correct_formula` 不知道时
留空。例外表必须包含全部 15 个 ID，某个工作簿没有合理例外公式时第二列留空：

```csv
instance_id,exception_cells
independent_001,Sheet1!G7;Summary!B12
independent_002,
```

## 严格时序

1. 出题人先只交付公开的错误工作簿和两列 manifest；
2. 模型开发者完成 V5.2 三轮、选择、冻结、Git 提交与推送；
3. 用户运行 `run_v4_v52_blind_lock.cmd --workers 24`；
4. 只有看到 `prediction_lock.json` 成功生成后，出题人才释放两个私密 CSV；
5. 用户运行 `run_v4_v52_blind_score.cmd`；
6. 15 例全部计入结果，不删除不利案例。

出题人不得提前告诉模型开发者错误坐标、类型、修复公式或哪些公式是合理例外。工作簿不得包含
个人信息、学校内部信息或无权公开的公司数据。
