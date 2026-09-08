# V5.1.9-development：保留完整候选域的依赖联合修复

当前状态：G2、G3、G4、G5 及 G6 最终审计通过；V519 Git 交付正在准备。
本文件记录的是条件性合成证据，不构成第三方业务盲测或生产安全声明。

## 1. 实现与接口

新增 `formulaguard/v5_1_9_development.py`，复用 G1 组件表及 V518 独立候选路径，
增加预算搜索、完整空间前缀证书、输入重建回放和原子修复组。
原候选域包含全部 bounded edge proposals、signature 去重及“不改”选项；
数值相同但公式不同的赋值仍计为不同解。定位排名及候选档案保持完整。

本地 Python 统一入口新增 `method="v5.1.9-development"`，兼容下划线及紧凑
版本别名，支持 v4、v511 后端和 structural/review_only/reject_all 策略。
默认入口保持原状。此 API 是 Python 函数，不是外部 HTTP 服务，不需要密钥，
也不自动写回 Excel。需要完整证书时调用模块级 `diagnose_v5_1_9_development`
保留 `JointDiagnosis`，再使用 `verify_unique_solution` 回放。

只有完整覆盖原空间且唯一时才产生新的联合接受；单解后中断、未知求值或多解
不能接受。非接受策略保留诊断证据但不给接受动作。批准无效时没有新的约束
驱动接受；旧 legacy 边界单列并与原行为核对。

每个诊断使用局部计数包装器，准备失败和回退保留消耗。节点上限 10000、
叶求值 4096、准备求值 4096、每组件状态 256。初始约束求值计入 V519 准备账本，
这是与 V518 历史审计口径的一次调用差异；组件节点和逐格节点也不是相同工作量。

证书绑定输入、批准、日期、运行环境、可信配置、后端/策略、原域和组件表身份。
回放从实际输入重建所有表和界限，验证混合进制前缀连续覆盖，复算保留叶，
核对唯一赋值、计数与全部原子决策；定位参考默认重算，实验可传入刚重算的完整排名。

## 2. G2–G4 证据

| 阶段 | 已观测结果 |
| --- | --- |
| G2 | 72 个 G1 工作簿、双后端 144 个唯一诊断全部回放；24 个固定最小门槛案例全部通过 |
| G3 | 全部 192 个已揭示 V518 工作簿、384 次诊断；原 84 次唯一接受全部保留并回放；零不安全组 |
| API | G3 后新增统一入口，18 项别名/后端/策略检查通过 |
| G4 | 固定 12 个 13 格真实 pair/chain 工作簿在两后端全部改善；V516 实际穷举 196608 个状态 |

G3 每个后端：开发集唯一组由 18 增至 21，原确认集由 24 增至 36。
原确认集新增的 12 个依赖案例属于既有零系数引用模板，仅作回归收益；
G1/G4 的非零依赖及 G5 新生成器提供另列的真实数值耦合证据。
弱界限仍有预算拒绝，全部错误格保留在分母。后端重复不增加不同工作簿数。

G2/G3/G4 的源码快照分别保留在 `results/v519_g2_source_v1/`、
`results/v519_g3_source_v1/`、`results/v519_g4_source_v1/`。API 在 G3 后有意新增，
复核先前阶段时应使用对应快照，不用当前目录替代历史执行上下文。
V518 及更早模型、G1 组件源码、历史输入和受保护数据均未改写。

## 3. 串行成本

固定 product/pair，16/24/32 格、两后端、五次重复，交错执行 V518/V519，
共 60 次测量；每次重复重算排名并在两个模式间公平复用。
32 格的中位秒数如下：

| 后端 | V518 修复阶段 | V519 修复阶段 | V518 内存流程总计 | V519 内存流程总计 |
| --- | ---: | ---: | ---: | ---: |
| V4 | 4.8733 | 0.1882 | 19.0364 | 14.3595 |
| V511 | 4.8701 | 0.1823 | 5.0707 | 0.5316 |

总计包括内存输入构造、排名、诊断、唯一证书回放及序列化，不含 XLSX I/O。
V518 在这些样例中超预算，V519 唯一完成；不是相同成功结果之间的纯速度比较。
V4 排名仍是主要成本。V519 32 格唯一证书约 4170 字节；V518 超预算搜索记录
约 525006 字节，两者完成状态不同。RSS 是进程高水位，不是独立求解器分配量。

两次单独的 32 格观察器运行将候选准备、界限/表准备和搜索/分派/初始检查余项
分开记录。插桩后的诊断为约 0.59–0.64 秒，不能与未插桩中位时间混用。
所有原始测量、范围和观察器数据见 `V519_SERIAL_BENCH_V1/result.json`。
五次重复不支持生产 P95 保证，也不证明真实工作簿延迟。

## 4. G5 开发与确认

已完成 12 类样例的 36 项小空间穷举预检和 12 项流程攻击/标签隔离测试。
开发矩阵为 51 个工作簿、612 次诊断，评分通过；两个后端分别由 V518 的
252/735（34.29%）提高至 V519 的 540/735（73.47%），零不安全接受组，
排名及候选变化为零。关闭组件优化与基线覆盖相同，三种限制接受模式均无接受。
冻结确认包含 144 个工作簿、1728 次诊断；评分和原始事务审计已完成。
V4/V511 主模式各正确修复 2016/3420 个错误格（58.95%），各 72 个接受组，
零不安全组；定位排名和候选域变化均为零。低预算、review_only 和 reject_all
均无接受动作，预算/歧义/无解/无效批准均保留在完整分母中。
首次确认预测在会话运行环境中断后仅留下 1328 个分片，无完整预测锁。
恢复时核实进程已不存在，454 个冻结文件、依赖和数值环境一致；未读取确认标签。
未完成分片保留在 `results/v519_confirmation_predictions_interrupted_v1/`，
使用同一冻结种子、输入、配置重新完整预测，不拼接未锁定的部分结果。
先冻结源码/协议/环境，再生成新种子，锁定完整预测并验证全部证书后才读取标签。

## 5. 边界与剩余验证

数值优化沿用经核对的 CPython 3.11.16、math 二进制及 binary64 舍入前提，
原 aggregate 成员数不超过 4096、最大绝对贡献总和不超过 `2**500`。
更换环境、超限组件、循环/未知求值和弱界限可能回退或拒绝。
这些条件性实现与合成实验不等于任意平台的形式化证明或第三方业务盲测。
观察到零不安全组不意味着总体风险为零；真实外部批准的正确性仍是实验假设。

最终全仓 pytest：1196 passed、1 skipped、91 subtests；Ruff 全部通过。
G5 确认原始证据和 G2–G5 历史快照的 G6 审计已通过。最终提交推送和远端核验
仍需 GitHub SSH 认证，未在本轮自动绕过认证。
阶段 plan 和检查日志分别在 `V519_G*_PLAN.md`、`V519_CHECKS/`。

## 6. 命令与证据路径

以下命令从仓库根目录执行，现有输出目录不允许覆盖。重跑时应使用新的输出
目录，并保留本轮冻结文件和原始输入；重新生成随机确认种子会产生另一轮实验。

```bash
.venv/bin/python -m scripts.validate_v519_g2 --output research/V519_G2_V1 --workers 4
.venv/bin/python -m scripts.validate_v519_regression --output research/V519_G3_V1 --workers 4
.venv/bin/python -m scripts.validate_v519_milestone --output research/V519_G4_V1 --workers 4
.venv/bin/python -m scripts.benchmark_v519_components --output research/V519_SERIAL_BENCH_V1
.venv/bin/python -m scripts.evaluate_v519_confirmation freeze --output results/v519_freeze_v1
.venv/bin/python -m scripts.evaluate_v519_confirmation build --stage confirmation --lock results/v519_freeze_v1/source_lock.json --output results/v519_confirmation_release_v1
.venv/bin/python -m scripts.evaluate_v519_confirmation predict --release results/v519_confirmation_release_v1 --lock results/v519_freeze_v1/source_lock.json --output results/v519_confirmation_predictions_v1 --workers 4
.venv/bin/python -m scripts.evaluate_v519_confirmation score --release results/v519_confirmation_release_v1 --lock results/v519_freeze_v1/source_lock.json --predictions results/v519_confirmation_predictions_v1 --output research/V519_VALIDATION_V1 --workers 4
.venv/bin/python -m research.V519_FINAL_AUDIT --output research/V519_FINAL_AUDIT_V1
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

G2/G3/G4 的历史执行源码以各阶段源锁和对应快照为准。冻结后的正式实验源码
在 `results/v519_freeze_v1/source/`，完整预测在 `results/v519_*_predictions_v1/`。
最终审计输出会归档本轮合成输入、批准、已授权标签、源锁、预测哈希、接受组
和分层统计；大体积原始预测与源码快照继续留在被 Git 忽略的 `results/`。
