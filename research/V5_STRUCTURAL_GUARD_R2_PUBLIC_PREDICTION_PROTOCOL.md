# V5 Structural Guard R2 PUBLIC 预测协议

状态：PUBLIC 已接收、SECRET 未接收、外部重算待完成。

## 1. 固定模型

本轮只运行 `formulaguard/v5_structural_guard.py` 中的 V5 Structural Guard R2，不运行
或融合其他模型。模型及其直接依赖必须与提交
`2232a870e3be089650ccd1676049e6c5c35cd692` 中的字节完全相同。PUBLIC 接收后禁止根据
工作簿内容修改模型、默认参数、组边界、候选规则、排序或拒绝门控。

PUBLIC 的归档 SHA-256 为
`6a003fcbc5786168a8cbd00e002ea407fe7d37f7920b3c9123999fc0784c75b3`。归档在模型提交后
才提供，但预测运行器和本协议在 PUBLIC 结构可见后才加入仓库；因此本轮只能称为
“锁定模型上的无标签 PUBLIC 预重算工程预测”，不能称为完整预登记的最终外部盲测。

## 2. 输入边界

运行器只能读取：

- `PUBLIC/manifest.csv`；
- `PUBLIC/SHA256SUMS.txt`；
- `PUBLIC/workbooks/*.xlsx`；
- 原始 PUBLIC ZIP，用于验证解压内容未变化。

PUBLIC 必须恰有 360 个匿名案例、30 个匿名模板簇且每簇 12 例。manifest 字段固定为
`case_id,cluster_id,workbook_path,workbook_sha256,file_format,integrity_status`。任何标签、
正确公式、错误类型、源单元格、原始工作簿或 SECRET 内容都会使运行器拒绝执行。

## 3. 输出和锁

每个案例保存完整公式排名、分数、候选公式、组状态和证据。运行器必须验证：

- 输入工作簿哈希与 manifest 和 `SHA256SUMS.txt` 同时一致；
- 模型返回全部公式格且无重复；
- 模型不修改内存中的原公式；
- 每个组的状态和原因一致；
- 全部 360 个预测分片存在后才创建预测锁。

排名、候选和证据进入确定性分片哈希；运行时间单独记录，不影响复现哈希。两次独立
运行必须产生相同的 `combined_shards_sha256`。

## 4. 当前可报告内容

没有 SECRET 时只报告解析完成率、公式数、候选行动率、接受/拒绝组数、拒绝原因、
完整排名和重复运行一致性。不得报告命中率、修复正确率、控制误报率或泛化通过。

当前 manifest 将全部工作簿标记为 `external-recalc-pending`。外部重算会改变文件时，
必须把重算后的 PUBLIC 作为新输入重新承诺哈希和重新生成预测锁；本轮预测不能替代
最终评分回执。

## 5. 固定命令

```bash
python scripts/run_v5_structural_guard_public_predictions.py \
  --public data/external/v5_structural_guard/raw/public_pre_recalc/PUBLIC \
  --source-archive data/external/v5_structural_guard/raw/V5_Structural_Guard_R2_PUBLIC_PRE_RECALC.zip \
  --output results/v5_structural_guard_public_pre_recalc/run_a \
  --workers 16
```
