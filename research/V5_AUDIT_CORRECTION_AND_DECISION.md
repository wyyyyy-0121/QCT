# FormulaGuard V5 开发运行审计修正与决策

## 修正范围

V5完整开发运行已完成，原始模型输出、参考结果和原始CSV均保持不变。首次审计将每个事件的
`v5_raw.csv` 中 `v4_final_rank` 与锁定的V4事件级名次直接比较。该比较只适用于恰有一个标注
公式的事件。

对于多个标注公式的Enron事件，事件名次是所有标注公式中的最小名次；V5行中记录的
`v4_final_rank` 则属于取得V5最小名次的那一个公式。这两个公式可能不同。以
`enron_event_19` 为例，事件有42个标注公式：锁定V4事件最小名次为1，而取得V5最小名次的
公式在V4中为第17名。两种模型的事件级最小名次均为1，因此这不是V4漂移。

审计脚本现只对单标注公式事件执行该嵌入V4名次检查；多标注公式事件记录为“不可直接比较”。
未修改`formulaguard/v5.py`、原始评测CSV、参考CSV或门槛数值；只重新生成审计JSON。

## V5开发结论

**决定：拒绝V5，不冻结，不开发V5-R2。**

修正后的审计不会改变以下真实模型失败：

- Enron 30事件：Top-5 = 14/30 = 0.4667，低于预登记目标0.467的显示阈值；
- Enron MRR = 0.3418，低于预登记下限0.363；
- 相比冻结V4，配对MRR差为 -0.0407，bootstrap 95%区间为[-0.1009, -0.0046]；
- V5使4个原来位于V4 Top-5的Enron源事件下降（4→9、1→4、2→3、2→3）。

V5在18例已揭晓合成开发集上的Top-5为100%、MRR为0.9722，48份干净表确认报警率为
2.08%，但这不足以抵消真实语料安全回归失败。依据`V5_METHOD_SPEC.md`的停止规则，
论文应保留V4-r1作为当前最终模型，并把V5如实写成一次有记录、可复现的开发失败案例。

## 可复现性指针

本决定对应的修正审计文件为
`results/v5_development_audit/v5_development_audit.json`，SHA-256为
`d875f0b97d1e6c67ce5ecc90228fa5730519882f465e2fb2d42cfd8e4c75dee9`。

- 合成合并矩阵：`results/v5_development_synthetic/external_raw.csv`，
  SHA-256 `383b83151e188aaedca410b1aa1a7de83ca065f65f8628ff981447d77135d833`；
- Enron合并矩阵：`results/v5_development_enron/external_raw.csv`，
  SHA-256 `02314826c33aea94c2c6330dacdc326140b32e57167c6c8641d2bd4f97c46421`；
- 干净表汇总：`results/v5_development_clean/v5_clean_summary.json`，
  SHA-256 `216f544b74e8cd79ec3330da0aaf44144a113037ad2591aaa6a9a103005fe039`。
