# FormulaGuard v4 独立盲测协议

## 目的

本协议只用于v4确认性验证。既有30个Enron事件已经参与模型观察，因此只能作为
回顾性开发数据，不能再次充当盲测证据。

## 数据准备

请由一名不参与模型开发的人准备6--12份非敏感工作簿，每份制造1个仍能返回正常
数值的静默公式错误。准备两份清单：

1. 无标签清单只含`instance_id,workbook`，放入项目目录；
2. 标签清单含`instance_id,source_cell`或`source_cells`，保存在项目目录外。

错误制作者不得告诉算法开发者错误位置。工作簿可以进入项目目录，但文件名和表格
内容不得直接暴露错误格。每个事件应记录原始表格来源、修改者、修改日期和允许使用
条款；这些记录在揭盲后加入证据台账。

## 第一步：标签打开前冻结预测

```bat
cd /d D:\code\QCT
python scripts\run_v4_blind_predictions.py ^
  --manifest data\blind_v4\blind_manifest.csv ^
  --output results\v4_blind_locked
```

脚本拒绝包含`source_cell`、`correct_formula`、`error_type`等字段的清单，也拒绝覆盖
已有输出。它保存所有公式的完整排名，并生成`prediction_lock.json`。锁文件创建后，
不得编辑排名或元数据。

## 第二步：揭盲并评分

预测锁生成并另行记录其SHA-256之后，才可取得标签清单。标签文件可继续留在项目
目录外。运行：

```bat
python scripts\score_v4_blind_predictions.py ^
  --lock results\v4_blind_locked\prediction_lock.json ^
  --labels D:\outside_qct\v4_blind_labels.csv ^
  --output results\v4_blind_scored
```

评分脚本先验证完整排名和元数据哈希；任何预测后修改都会使评分失败。随后分别报告
graph、pattern、v2、v3和v4的Top-1、Top-3、Top-5、MRR与EXAM，并进行逐事件配对。

## 解释边界

- 少于15个事件时，只称独立案例研究，不使用“统计上稳定优于”；
- 无论结果是否提升，都保留锁文件、完整排名、标签哈希和失败案例；
- 揭盲后不得再修改v4并在同一批数据上重新声称确认性结果；
- 若需要继续开发，当前盲测自动降级为下一版本的开发数据，并另建新盲测。
