# FormulaGuard 独立小样本盲测协议

## 目的与定位

这是一项补充性的案例研究，不替代 864 例合成实验，也不与 Enron 的 20 个
冻结事件合并计算指标。它的价值是验证：在本项目生成器之外，由独立的人在
真实、非敏感工作簿中制造的静默错误上，系统是否能在不知道标签时给出可
审查的排序，并且不会把已知正确的例外公式一律排入人工 Top-5 检查队列。

无论结果好坏，所有案例、标签和失败都保留。样本小于 15 时只作为盲测案例
集报告，不作总体显著性推断。

## 角色隔离

1. **出题人**（同学或老师，非 FormulaGuard 开发者）选择 6—12 份非敏感、
   可分享的 `.xlsx` 工作簿；每份只注入一个仍能得到普通数值的公式错误。
2. **运行者**只收到错误版工作簿与公共清单，运行排名程序；公共清单不得
   写入错误单元格、正确公式、错误类型或原文件。
3. 出题人在预测文件及哈希生成后才解封私有标签；任何人不得在解封前根据
   排名结果换题、删题或改公式。

私有标签应放在工作区外，例如 `D:\FormulaGuard_Blind_Labels\`，不要上传到
本项目、不要粘贴到聊天中。工作簿须去除个人信息、成绩、账号和商业机密。

## 预登记规则

- 每份表格一个错误事件；标注为多格范围时仍计作一个事件。
- 至少一半错误不得是“把某引用简单加一或减一”即可逆转的错误；优先包括
  范围端点、运算符、绝对引用、跨表引用或复制偏移。
- 每份表至少标注一个**正确但看似例外**的公式，例如首行种子、小计、税率
  例外、跨表汇总或季度末调整。它不是错误，不得为取得好看结果而删除。
- 冻结比较方法：`formulaguard_v3_real`、`graph`、`pattern`；候选数固定为15。
- 主指标：Top-1、Top-5、MRR、EXAM；正确例外报告其进入 Top-5 人工审查队列
  的比例（`top5_review_exposure`），不把它误称为未校准阈值下的“误报率”。
- 正确公式如被保存，可额外评价候选修复精确匹配；未知时不评价修复。

## 文件格式

公共目录（可放在项目内）：

```text
data\independent_blind\public\
  manifest.csv
  workbooks\case01.xlsx ...
```

`manifest.csv` 只能有：

```csv
instance_id,workbook
case01,workbooks/case01.xlsx
```

私有标签（工作区外，由出题人保管）：

```csv
instance_id,source_cell,correct_formula,error_formula,error_type,author_code,created_at
case01,Sheet1!F18,=SUM(F5:F17),=SUM(F6:F17),range_boundary,teacher_A,2026-08-20
```

可选正确例外标签：

```csv
instance_id,correct_exception_cell,rationale
case01,Sheet1!F5,季度首行使用期初余额，公式正确
```

## 执行

### 1. 未读标签的预测冻结

```bat
cd /d D:\code\QCT
python scripts\run_unlabeled_blind.py --manifest data\independent_blind\public\manifest.csv --output results\independent_blind\predictions --methods formulaguard_v3_real,graph,pattern --candidate-limit 15 --workers 8
```

确认生成 `predictions.csv` 和 `prediction_manifest.json`。后者包含公共清单、
预测文件、冻结配置和代码的 SHA-256；在解封前不得修改预测文件。

### 2. 解封后审计

```bat
cd /d D:\code\QCT
python scripts\audit_unlabeled_blind.py --predictions results\independent_blind\predictions --labels D:\FormulaGuard_Blind_Labels\labels.csv --negative-labels D:\FormulaGuard_Blind_Labels\correct_exceptions.csv --output results\independent_blind\audit
```

审计器会拒绝预测文件哈希与冻结清单不一致的情况，并输出逐事件排名、汇总
指标和正确例外的 Top-5 审查暴露。论文只能把它写成独立小样本案例研究。
