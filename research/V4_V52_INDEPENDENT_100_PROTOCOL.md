# V4/V5.2 扩展独立验证协议（100 例合并集）

## 证据边界

公开包共含 100 个工作簿，其中 `independent_001` 至 `independent_015` 已在
Cohort-1 中揭晓，因此不能再次作为新盲测。`independent_016` 至
`independent_100` 共 85 例构成新的 Cohort-2 独立验证证据。论文必须分别报告：

1. Cohort-1（15 例，既有独立结果）；
2. Cohort-2（85 例，新独立结果，主要扩展证据）；
3. 合并 100 例（次要汇总，不冒充 100 例全新盲测）。

## 标签释放前承诺

标签、例外表及私密压缩包的 SHA-256 已在
`research/V4_V52_INDEPENDENT_100_COMMITMENT.json` 中记录。预测只允许使用冻结
V4 与冻结 V5.2-B，公开 manifest 只能包含 `instance_id,workbook` 两列。

## 运行顺序

1. 提交并推送本协议、承诺文件和锁定代码；
2. 运行 `run_v4_v52_blind_100_lock.cmd --workers 24`；
3. 确认新 `prediction_lock.json` 成功写入后，才能取得私密 Batch-2；
4. 将承诺哈希对应的两个 CSV 解压到 `D:\FormulaGuard_Blind_Labels_100\`；
5. 运行 `run_v4_v52_blind_100_score.cmd`；
6. 100 例全部保留；Cohort-2 的 85 例单独统计置信区间与失败案例。

评分命令会拒绝哈希不匹配的标签或例外表。Review@6 仍只是额外人工复核指标，
不得表述为 Top-5 改善。
