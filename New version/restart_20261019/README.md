# HybridGuard 反思后重启

本目录承接用户2026-10-19确认的新研究顺序。先读[论文输入审计](PAPER_INPUT_AUDIT.md)、[历史失败复盘](FAILURE_REVIEW.md)与[研究协议](RESEARCH_PROTOCOL.md)，当前完成程度见[STATUS.md](STATUS.md)。原模型及旧实验保持只读，`/home/ayaka/code`未修改。

目前完成：原论文输入边界复核、dev32独立指标审计与拒绝采纳、dev33资格审查、真实xlsx只读推理和默认8工作进程批处理。自然开发证据来自cv-500、EPA、Tuxprogrammer/msu_ece4723三个独立来源，至少4个模板家族和3类错误机制；满足有限开发实验准入，但不等于最终验证充分或准确率达标。原模型和dev11仍冻结。首轮E1-E3结果见`E1_E3_RESULTS.md`。

## 运行单个工作簿

```bash
cd '/home/ayaka/hybridguard/New version/restart_20261019'
/home/ayaka/hybridguard/.venv/bin/python tools/predict_workbook.py \
  '/absolute/path/input.xlsx' --output '/new/path/prediction.json'
```

有可信预先声明的平行表时，显式追加 `--parallel-sheets A B C D E`。不自动猜测这些表业务相同。输出包含论文与dev11全部逐格结果、候选、来源、原有证据及拒绝状态；源文件哈希验证不变。输出文件必须不存在；每个输入工作簿只读，另一个进程负责评分。不把不支持状态转换为正确。

## 批量运行

每个工作簿是一条JSONL任务，使用完整参数数组，避免shell拼接。命令和输入路径应为绝对路径；若不指定cwd，每个任务默认使用独立的输出目录。

```json
{"id":"book01","argv":["/home/ayaka/hybridguard/.venv/bin/python","/home/ayaka/hybridguard/New version/restart_20261019/tools/predict_workbook.py","/absolute/input.xlsx","--output","prediction.json"],"outputs":["prediction.json"]}
```

```bash
/home/ayaka/hybridguard/.venv/bin/python tools/batch_runner.py \
  --manifest '/absolute/tasks.jsonl' --output-dir '/new/run/directory' \
  --workers 8 --worker-memory-mib 1024 --timeout 300
```

`--worker-memory-mib`是按工作簿测量后设置的峰值估计。准入取70%的启动时可用内存，必要时降低并发；它不是硬内存限制。数值库线程固定1。每个任务保留combined.log、GNU time资源记录和输出哈希；总runtime包含成功、失败、超时、墙钟、完整时的子进程CPU总和、50ms采样并发RSS与吞吐。超时任务CPU若不能完整计量则明确记null，不能记零。

当前真实工作簿基准为 `workbook_benchmark_v3/comparison.json`：1/4/8进程输出字节哈希一致，8进程较1进程快5.62倍；8个小表在0.378秒完成、并发RSS采样峰值397MiB。历史输出对比单独见 `WORKBOOK_INTERFACE_PARITY.json`，保留浮点舍入差。早期烟测与采样失败证据仍保留，不用它们宣称准确率提升。

## 新证据

- `DEV32_METRIC_VERIFICATION.json`：复算7,713项指标，108项独立执行结果；42次不能证明的关系不计正确。重放依据为保留的首版277案例日志，未再运行一次耗时重放。
- `DEV32_EXACT_MATCH_SCORE.json`：保留原论文含等号全文本精确匹配口径；不能把关系等价分数混称原论文分数。
- `../followup_20261014/development/natural_weights_dev33_v1/`：原表锁、重放、修订取得回执、双解析器和布局审计；未认证任何自然错误。原文件和含第三方正文的差异留本地，git忽略。
- `source_evidence/EPA_ERRATA_RECEIPT.json`：3份官方勘误的URL与哈希；文档不是可评分原始/修订工作簿对。
- `EPA_ERRATA_FOLLOWUP.md`：较早的EPA文件追索记录；后续取得的历史版本对和更新后的逐格资格以`EPA_PAIR_AUDIT.md`为准。
- `source_evidence/NATURAL_REVISION_SEARCH.json`：3个成功查询、18个提交细查、5个含工作簿变化的提交；新增路径、删表、计算兼容错误和AI生成来源不能自动视为自然静默公式错误。
- `source_evidence/NATURAL_REVISION_SEARCH_20261019_2.json`：4个成功查询、19个提交细查、0个含工作簿变化的提交；该轮没有新增可审计来源。
- `STAMPZ_SEMANTIC_AUDIT.md`：StampZ原/修订版98个Hue公式存在一致的+5行偏移且修订改为同行；因原表输入和结果均为空，只记公式级候选，不能计准确率、覆盖率或自然来源准入数。原件未提交且全来源排除最终验证。
- `EPA_PAIR_AUDIT.md`：官方EPA历史版本的格式失败、揭示顺序和逐格证据边界；认证Flares!B39:B43及Oxidizers!D36。
- `METRICS_PAIR_AUDIT.md`：Software Metrics 28个非空数据行求和遗漏候选、冻结模型预测及替代公式未知状态；原始工作簿不公开。
- `E1_E3_RESULTS.md`：首轮E1冻结基线评分和独立Calc执行复核、E2停止决定、E3业务说明路线准入条件。E1复算工具为`tools/score_e1_metrics.py`，Calc核验为`tools/verify_e1_calc.py`；结果是已揭示开发审计，不是盲测。
- `E1_E3_PREREGISTRATION.md`：首轮有限实验的问题、控制、指标与停止条件。实现和阈值冻结，实验开始前须补齐标签。

新运行器测试：`python -m unittest discover -s tools -p 'test_*.py' -v`。这4项覆盖输出隔离、线程限制、失败/超时保留、路径与重名校验和已有证据保护。历史研究321项测试的记录在dev32审计中核对，本轮没有将其冒称为重新运行。
