# V5-PSL 240+120 单保管人锁定确认协议 v2

## 1. 证据定位

本协议用一名未参与 FormulaGuard 模型开发的独立保管评测人，替代 v1 中难以执行的
六名制题人、两名逐例复核者和独立保管人安排。保留 30 个未见模板、240 个错误、
120 个控制、预测前双归档承诺、标签后释和一次性评分。

正式名称只能写成“单保管人盲持的外部模板确认”或
`single-custodian held-out external-template confirmation`。不得写成六人、多中心、
多标注者一致性或完全独立复现。统计单位始终是 30 个模板簇，不把 360 个变体冒充
360 个相互独立的自然样本。

修订时间、未查看结果声明和降级理由见
`V5_PSL_THIRD_PARTY_AMENDMENT_V2.md`。旧 v1 制题人包不能直接进入 v2；不得通过
伪造人员 ID 或复制声明字段使旧包通过。

## 2. 唯一外部角色

只需一名独立保管评测人，稳定匿名 ID 同时写入声明的 `custodian_id` 和全部案例的
`steward_id`。该人员必须：

- 未参与 V4、V4.2、V4.3、V5-PSL 的设计、实现、调参或公开压力分析；
- 在候选锁前不向开发者提供模板、工作簿、源格、错误/控制身份或案例理由；
- 未取得任何模型输出，并且不在自己的工作簿上运行 FormulaGuard；
- 负责或监督模板选择、案例计划、重算、许可/脱敏核对、打包和标签保管；
- 在真实计算引擎中重算全部案例，并为歧义错误和合法例外控制写出逐例理由；
- 认可单人判定不能提供标注者间一致性证据，该限制必须进入论文。

项目开发者、作者和本仓库中的自动化代理都不能充当该角色。

## 3. 固定设计

- 30 个开发阶段未见模板，每个模板 12 例；
- 每模板 8 个错误和 4 个控制，共 240 错误、120 控制；
- 六类错误各 40 个；每模板 6 个可识别单源错误和 2 个歧义错误；
- 60 个歧义错误包括 30 个单源合法例外近似和 30 个对称多源块；
- 每模板 2 个普通控制和 2 个合法例外控制，共 60+60；
- 模板来源只能是 `steward_owned` 或 `licensed_public`，每个模板都要有许可或所有权编号；
- 每个可识别错误和单源歧义只改变 1 个公式；对称多源错误改变 2 至 5 个公式；
- 控制不得改变公式或填写源格。

外部人员数量不再是设计平衡变量。公式类型、歧义层、控制层和模板簇仍按上述固定
配额审计。最终置信区间按 `template_id` 做固定 10,000 次聚类 bootstrap。

## 4. 外部原始目录

```text
cases.csv
third_party_declaration.json
workbooks/*.xlsx
originals/*.xlsx
```

不再存在 `reviews.csv`。`cases.csv` 必须严格使用
`V5_PSL_THIRD_PARTY_CASES_TEMPLATE.csv` 的字段顺序。`adjudication_rationale` 对 60 个
歧义错误和 60 个合法例外控制必须非空；普通控制和可识别错误可以为空。

声明严格使用 `V5_PSL_THIRD_PARTY_DECLARATION_TEMPLATE.json`。四个外部证据文件不
进入 Git，但必须在打包前计算 SHA-256 并填入声明：

- `permission_evidence_sha256`：逐模板许可或所有权清单；
- `anonymization_evidence_sha256`：脱敏检查记录；
- `case_plan_sha256`：任何第三方预测前冻结的 360 例计划；
- `template_overlap_evidence_sha256`：30 个模板与开发/公开压力模板不重合的审计。

## 5. 打包器的硬检查

打包器只接受无宏 `.xlsx`，拒绝连接、外部链接、公式格集合变化、非公式内容变化、
可见性变化、数值格式变化和声明外公式差异。它还验证：

- 精确的 240+120 构成、六类各 40、30 个模板各 12 例；
- 全部 `steward_id` 等于声明中的唯一 `custodian_id`；
- 歧义和合法例外理由完整，四个证据哈希格式有效；
- 公开开发公式变换签名不与第三方案例重合；
- 内部求值器完整覆盖时，错误至少改变一个实算公式值；
- PUBLIC 只有匿名 ID、随机工作簿名和完整性信息，SECRET 才包含标签和原表。

打包器不生成工作簿、不运行 FormulaGuard，也不能证明单人语义判断等同于多人共识；
复杂公式仍由声明中的独立计算引擎重算负责。

## 6. 固定锁定顺序

1. 文献门 v3 以“11 篇全文 + 2 篇封闭访问披露”通过；
2. 六个公开语料压力与四项消融完成，允许的机制修订结束；
3. 保管人完成原始集，只交付 PUBLIC 与 SECRET 的 SHA-256；
4. 开发者提交干净工作区并生成候选锁；
5. 保管人释放无标签 PUBLIC；
6. 四个预声明方法写出完整排名，验证器生成预测锁；
7. 保管人释放 SECRET，评分器只打开和评分一次；
8. 不得删除案例、换模板、改阈值、重打包或根据标签创建同队列版本。

保管人在项目外运行：

```bash
python scripts/build_v5_psl_third_party_pack.py \
  --raw /custodian/raw_360 \
  --output /custodian/package \
  --pseudonym-key-file /custodian/opaque_key.bin \
  --development-signatures /custodian/development_formula_change_signatures.txt
```

候选锁前只能把 `package_receipt.json` 中两个归档 SHA-256 交给开发者。PUBLIC 和
SECRET 必须分两次释放。开发者在候选锁后运行：

```bash
python scripts/run_v5_psl_predictions.py --public /released/PUBLIC \
  --candidate-lock results/v5_psl_candidate_lock.json \
  --output results/v5_psl_independent_predictions --workers 24
python scripts/verify_v5_psl_prediction_lock.py --public /released/PUBLIC \
  --candidate-lock results/v5_psl_candidate_lock.json \
  --predictions results/v5_psl_independent_predictions
```

只有 `prediction_lock.json` 写入成功且 `secret_release_authorized=true`，保管人才可
释放 SECRET。随后只运行一次：

```bash
python scripts/score_v5_psl_blind.py --public /released/PUBLIC \
  --candidate-lock results/v5_psl_candidate_lock.json \
  --predictions results/v5_psl_independent_predictions \
  --secret-zip /released/FormulaGuard_V5_PSL_SECRET_360.zip \
  --output results/v5_psl_independent_scored
```

评分器只写 `promotion_allowed`，不会自动提交代码、创建正式配置或增加 Git 标签。

## 7. 你现在要做什么

你只负责以下事项，不制作或查看第三方标签：

1. 完成六语料公开压力与四项消融；
2. 找到一名满足第 2 节条件的外部保管评测人；
3. 把本协议、两个 JSON/CSV 模板、打包脚本和开发变换签名交给对方；
4. 候选锁前只接收两个归档 SHA-256；
5. 按第 6 节顺序接收 PUBLIC、锁预测、再接收 SECRET。

外部保管评测人需要准备 30 个合法模板和 360 对工作簿，填写 `cases.csv` 与声明，
在其环境中运行打包器，并保管匿名密钥和 SECRET。

## 8. 没有任何外部人员时

仍可完成文献门、六语料公开压力和消融，并提交一个普通的开发快照；但没有真实的
PUBLIC/SECRET 归档哈希就不能运行候选锁脚本，不能生成盲持 SECRET，不能把
`promotion_allowed` 设为真，也不能使用
`V5-R1`、第三方独立验证或外部盲测通过等表述。该路线必须在论文限制中写明
“尚无独立锁定确认”，不能用项目自己生成的 360 例替代。

## 9. 当前状态

仓库只含 v2 协议、空模板和工具。独立保管评测人、30 个未见模板、360 份工作簿、
归档承诺、候选锁和评分回执目前均不存在。
