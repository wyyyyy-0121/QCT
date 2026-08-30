# FormulaGuard DRFV U0 语料门结果

日期：2026-08-31  
协议：`formulaguard_drfv_preregistration_v1`  
构建器：`formulaguard_drfv_corpus_build_v1`  
结论：U0 失败，DRFV 按预注册停止，未训练模型

## 输入隔离

- SpreadsheetBench v1 固定归档 SHA-256：
  `9cf7228b54f1edcdd4b372eb736774adf29cb4f804c9920229bac6c154833399`；
- input-only 接收器绑定提交 `0cb6a4daba79ae17b38d9993618bc48314b71c89`，从 912 个
  任务目录抽取 2,726 个 `_input.xlsx`；
- 2,729 个 `_answer.xlsx` 只在 tar 成员表中计数，未读取、未抽取；任务 JSON 只计算
  字节哈希，未解析 instruction、answer_position 或其他字段；
- 结构画像绑定提交 `c1e4610e3896d393ac8e6f5334b52a292b259251`，使用 24 进程；
- 故障标签、答案工作簿、V4 排名、单元格文字、原始数值、工作表名和保密数据输入均为空。

## U0 数量

| 项目 | 结果 | 预注册门 | 判定 |
|---|---:|---:|---|
| 原始 input 工作簿 | 2,726 | 仅清点 | - |
| 可用工作簿 | 625 | - | - |
| 已排除：无公式 | 1,593 | - | - |
| 已排除：可解析比例低于 50% | 508 | - | - |
| 保留的唯一字节工作簿 | 607 | >=300 | 通过 |
| 保留结构组 | 219 | >=100 | 通过 |
| 唯一工作簿可解析公式 | 74,570 | >=100,000 | **失败** |
| 达到单簿解析门的工作簿比例 | 22.93% | >=80% | **失败** |

全部 2,726 个 input 中有 1,133 个含公式，公式总数 532,789，可解析总数 140,953；
这些原始总数不能替代门槛口径。U0 按唯一字节、单簿至少 50% 可解析并删除已知重合
分量后的 74,570 个公式判断。

## 去重与拆分审计

- 内部连边 679：精确字节 1、精确结构 449、近公式多重集 229；
- 与既有 Gate 2/CWRP 安全画像连边 48，直接连接 17 个工作簿；
- 3 个重合结构分量、17 个工作簿被整组删除；
- 剩余 219 组按冻结规则得到 153/33/33 个 train/calibration/internal-test 组；
- 因 U0 已失败，这些拆分没有生成训练样本，也没有进入模型训练或测试。

## 不可变回执

- intake manifest SHA-256：
  `bb01edd4a58f80a7f26f6b3051f3bdbc6983b2a5a47a23d185bcd07cf2a4f42d`
- intake receipt SHA-256：
  `82e1aeb41d9c3acd8c5554d9d0f86a6dc8c3bf90e6bce54c26521ea3e1b0e97a`
- corpus manifest SHA-256：
  `0e1228992fccf6b13961e397b944133db83dcde72b5372af5c36cd54306e71ed`
- profile shards 聚合 SHA-256：
  `ab990c7fe386abd0dafafcf746e0992617bc7d65dd482705d483eabc66e5e9d6`
- corpus receipt SHA-256：
  `743461a31faf9734d38cbcb43dbf2a23cc1cf30076b8d83ffe22d3d7d6d5e789`

本地原始输入、画像和机器回执保存在 Git 忽略目录：
`data/external/model_discovery/corpus/drfv_spreadsheetbench_v1_inputs/`、
`results/drfv_spreadsheetbench_v1_intake/` 和 `results/drfv_corpus_v1/`。它们不得删除或
原地覆盖。

## 决定

按预注册，U0 任一硬门失败即停止：

- 不读取 SpreadsheetBench v1 answer 工作簿补数量；
- 不降低 100,000 公式或 80% 工作簿覆盖门；
- 不回收 CWRP 已揭晓测试折，不把 SpreadsheetBench 2 降级为开发数据；
- 不实现或训练 DRFV，不创建候选权重，不访问保密 `240+120`；
- 不把 607 个工作簿或 74,570 个公式描述成“接近通过”。

本结果只否定“以当前 SpreadsheetBench v1 input-only 语料执行该固定 DRFV 协议”的
可行性，不证明密度比验证思想普遍无效。若未来使用真正不同且许可、独立性和规模均
可审计的新语料，必须另写新研究代号和预注册，不能续写或重跑 DRFV v1。
