# V6 第三方 600 例协议

第三方在项目外准备工作簿，并运行 `scripts/build_v6_third_party_pack.py`。其秘密
模板配置至少包含 30 个未用于 V6 开发或验证的真实模板描述；秘密种子、正确
原表和标签不得进入 `D:\code\QCT`。最终模式**不会调用项目的合成生成器**，
只会验证和打包第三方已经制作好的 600 对原始/错误工作簿。内部生成器只允许
用于 `--limit` 工程测试，输出会明确标记为不得声称独立。

每类 100 例，共 600 例；其中 480 例由第三方在其未见模板上程序化产生，
每类 20 例（共 120 例）必须经过真实人工或半人工修改，并在 review ledger
记录实际调整、审核者和接受状态。最终 `case_manifest.csv` 使用
`research/V6_THIRD_PARTY_CASE_MANIFEST_TEMPLATE.csv` 的字段，工作簿路径必须
指向第三方秘密目录中的真实文件。

打包器逐例验证：原表与错误表只有源公式发生公式级变化；常量输入不变；两份表
均可解析并无显式计算错误；源公式存在到声明汇点的依赖路径；汇点数值确实变化；
清单中的正确公式和错误公式分别与两份工作簿一致。任一条件失败都会拒绝最终包。

冻结前只交付 `secret_precommit_sha256.txt` 的三个哈希。`v6-lock` 推送后才交付
PUBLIC.zip；联合 V4/V6 预测锁成功后才交付 SECRET.zip。公开清单严格只有
`instance_id,workbook` 两列。最终结果保留全部 600 例，不因解析、候选覆盖或
结果不好而删除；不支持案例只可带原因报告。

示例命令：

```bat
python scripts\build_v6_third_party_pack.py ^
  --output D:\FormulaGuard_V6_ThirdParty ^
  --secret-seed 由第三方保管的整数 ^
  --template-config D:\第三方秘密目录\templates.json ^
  --case-manifest D:\第三方秘密目录\case_manifest.csv ^
  --review-ledger D:\第三方秘密目录\manual_review.csv ^
  --final
```

最终设计门槛为：六类各 100 例、程序化 480 例、半人工 120 例且每类至少
20 例、至少 100 例跨表或长链、至少 100 例不能由简单邻格平移修复、至少
30 个不同第三方模板。所有 600 例都保留，不得因模型失败、候选不覆盖或结果
不好而删除。
