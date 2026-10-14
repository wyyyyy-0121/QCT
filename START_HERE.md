# QCT 项目入口

整理日期：2026-10-14。先看本文件定位材料；历史 README 和模型报告保留原文。

| 你要做什么 | 入口 |
|---|---|
| 查看最新论文原模型复现、开发结果及暂停交接 | [当前研究入口](New%20version/followup_20261014/README.md) |
| 阅读这次后续研究方案 | [后续研究计划](research/hybridguard_followup_20261014/PLAN.md) |
| 判断新仓库还是分支 | [仓库决策建议](research/hybridguard_followup_20261014/REPOSITORY_DECISION.md) |
| 查看本次指定的论文原稿 | `workspace/paper_snapshot_20261014/main.tex` |
| 查看原论文可复现实验 | `workspace/paper_experiments_202609/README.md` |
| 查看丘成桐论文写作与修订历史 | `workspace/paper_manuscripts_202609/README_提交文件说明.md` |
| 查看更早论文草稿和渲染记录 | `workspace/legacy_paper_drafts/` |
| 查看旧交付备份 | `workspace/paper_delivery_history/` |
| 查看后续 V5.1.9 工程状态 | `research/V519_G6_RESULT.md`、`research/V519_DEVELOPMENT_RESULT.md` |
| 查历史模型、数据及实验协议 | `research/`，配合原 `README.md` |
| 查原实验结果完整压缩备份 | `results_archive_20260914/README.txt` |
| 查看个人文件与保留的转换环境 | `/home/ayaka/2233/文件导航_20261014.md` |

原论文基线采用 HybridGuard 0.3.0／2026-09-04 handoff。QCT 后来的 V5.1.9 联合修复路线有独立的输入契约、约束和确认实验。两条线的成绩应分别引用。

## 目录用途

```text
QCT/
├── formulaguard/               历史与现有模型源码
├── scripts/                    命令与实验脚本
├── tests/                      原项目测试
├── research/                   研究协议、阶段报告、后续计划
├── data/                       输入与外部语料，保留原路径
├── results/                    当前留存的历史结果与回执
├── results_archive_20260914/    旧 results 完整压缩备份
├── deliverables/               原项目其他交付件
├── workspace/                  本机论文资料与写作历史
└── .venv/                      原项目运行环境
```

本次把散落的论文资料集中到 `workspace/`，保留带有实验锁的源码、数据和结果路径。根目录中的旧 `.cmd`、`.ps1` 入口属于 Git 历史，不在此次整理中重命名。

`workspace/` 和历史结果压缩包通过 `.git/info/exclude` 在本机排除，避免误提交个人稿件和大文件；这些本机目录不会随 clone 下载。远程仓库仍需要另行保存可发布的小型复现清单。`research/V519_G2_V1`、`V519_G3_V1`、`V519_G4_V1` 中原有未跟踪证据仍保留。

家目录中的 `HybridGuard-paper`、`HybridGuard-Yau2026`、`HybridGuard-paper-delivery-history` 兼容链接已移除。论文构建、校验与交付脚本已改用 `/home/ayaka/hybridguard/workspace/` 下的实际目录；历史日志、来源清单及交付压缩包保留原始路径记录。以后直接从上述 `workspace/` 入口进入。

以上目录整理记录属于早期阶段。最新论文原模型复现及开发副本已在 `New version/followup_20261014/` 保存；本次提交使用 `research/hybridguard-followup` 分支，上传后按用户要求暂停。目标尚未完成。
