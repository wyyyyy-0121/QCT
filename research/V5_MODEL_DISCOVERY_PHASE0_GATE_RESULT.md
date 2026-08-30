# FormulaGuard model-discovery Phase 0 Gate 0 回执

日期：2026-08-31
协议：`formulaguard_model_discovery_phase0_gate0_v1`
状态：通过，授权进入 Gate 1 文献与可运行基线检查

## 检查项

| 检查 | 结果 | 依据 |
| --- | --- | --- |
| 当前版本和历史版本身份无歧义 | PASS | `V5_MODEL_DISCOVERY_CURRENT_STATUS.md` |
| 推理输入不含标签、源格或语料语义 | PASS | `V5_MODEL_DISCOVERY_TASK_CONTRACT.md` |
| 事件、区域、工作簿、结构组和行动单位分开 | PASS | 任务契约第 4 节 |
| N1/N2/N3/U 数据角色已分层 | PASS | `V5_MODEL_DISCOVERY_DATA_LEDGER.json` |
| Phase 0 分组审计可复算 | PASS | `results/core_reset_b_phase0/data_audit.json` |
| 旧/新 `240+120` 保持不可读 | PASS | 账本 `label_status=unread`，输入审计无禁读路径 |
| 5pp 确认性主张的样本功效已评估 | PASS | `V5_MODEL_DISCOVERY_POWER_REPORT.json` |
| 功效不足时的动作已预先固定 | PASS | 增加模板或降级为探索性，不得事后放宽 |

## 事实摘要

- Phase 0 审计覆盖 220 个事件、147 个来源单元和 137 个结构组。
- Enron 只有 25 个工作簿组；它继续承担自然错误失败发现和迁移安全角色。
- 30 个最终模板组对 5 个百分点 Top-5 优势的保守最大检出功效约为 4.01%。
- 因此，最终盲测在没有增加模板前不能支撑强确认性 5pp 主张。

## 授权与禁止

已授权：方法卡、官方 ExceLint Linux 可运行性验证、共同输入适配和无标签原子信号
审计。
未授权：任何新继任模型实现、连续权重搜索、扩大 Top-k、旧试用运行或新保管人
数据读取。

## 下一门

Gate 1 需要完成方法卡、实现身份、输入/输出兼容性和指标映射；Gate 1 通过前不进入
Gate 2 信号分片。Gate 2 只允许一次评分，并按结果在完整排名、选择性辅助和最小附加
信息三个分支中选择一个。
