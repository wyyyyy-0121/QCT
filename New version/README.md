# 当前研究入口（2026-10-19）

本次反思后的[研究协议、失败复盘、实验状态与只读并行运行入口](restart_20261019/README.md)均位于 `restart_20261019`。论文原模型继续冻结作为对照，历史 `followup_20261014` 保留全部证据；自然来源不足时不继续调旧开发集。

以下为历史入口记录。

# HybridGuard 后续研究进展

更新时间：2026-10-14

## 最新研究主线

用户已明确后续以论文原模型 HybridGuard 0.3.0 为基线，目标为三类独立验证的建议精确率和正确修复覆盖率均达到90%。最新协议、原模型重跑及开发副本结果见 [后续研究执行入口](followup_20261014/README.md)。当前已完成原模型复现，首个副本仍未通过覆盖目标；最终验证尚未进行。下列V5.1.9报告保留为先前开发路线记录。

这里是从 QCT 迁移到 `hybridguard` 后的研究材料入口。当前阶段完成了当前模型重跑、Enron 回顾性回归和公开数据集核查。新数据已经下载并审计，尚未把新数据转换成模型输入，也没有用新数据给模型打分。

## 当前入口

- [当前模型结果](CURRENT_MODEL_RESULT.md)：V5.1.9-development 的开发集结果和 Enron 回归结果。
- [数据集核查](DATASET_REVIEW.md)：已下载数据的来源、数量、标签边界和适用性。
- [后续研究建议](FOLLOWUP_RECOMMENDATIONS.md)：下一轮实验顺序、修改重点、评价门槛和仓库安排。
- [结果推导审计](20261014_reports/DERIVED_RESULT_AUDIT.json)：由已锁定输出重新计算的关键数字和输入哈希。

三页中文阅读版已交付到 `C:\Users\hiuni\Desktop\`，文件名为 `HybridGuard_当前表现与后续研究建议_20261014`，提供 PDF、Word 和 TXT。本目录内也保留 [PDF](20261014_reports/HybridGuard_当前表现与后续研究建议_20261014.pdf)、[Word](20261014_reports/HybridGuard_当前表现与后续研究建议_20261014.docx) 和 [交付哈希](20261014_reports/DELIVERY_VERIFIED.json)。PDF 三页均已检查，Word 内容与生成文本逐项一致。

## 结果目录

- `20261014_v519_current_model/`：冻结、预测、评分、测试日志和指标。
- `20261014_v519_enron_retrospective/`：25 个 Enron 工作簿、两个后端的回顾性定位结果。
- `20261014_dataset_review/`：来源回执、下载包、ZIP 审计和标注清单。
- `20261014_reports/`：本页报告的推导脚本和审计结果。

## 版本边界

当前模型是 `V5.1.9-development`，运行时使用模型环境中的 Python 3.11.16。它与论文中原来的 HybridGuard 0.3.0 handoff 不是同一个实验版本。当前报告把论文旧结果、当前开发集结果和 Enron 回归分开记录，不把它们合并成一个总分。

本轮原模型保持不变，开发副本及研究证据提交到现有 `wyyyyy-0121/QCT` 仓库的 `research/hybridguard-followup` 分支。按用户要求，上传后暂停；交接见 [暂停记录](followup_20261014/PAUSE_CHECKPOINT.md)。

旧的 `research/hybridguard_followup_20261014/PLAN.md` 和项目根目录的 `START_HERE.md` 保留先前阶段记录；其中“未重跑”不再描述当前进度。查看本轮结果以这里的四份报告为准。
