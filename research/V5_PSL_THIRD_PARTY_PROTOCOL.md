# V5-PSL 240+120第三方锁定确认协议

## 证据边界

该数据由六名不参与模型开发的制题人和一名独立保管人准备。模型冻结前，开发者
只能取得PUBLIC和SECRET的SHA-256，不能取得工作簿、源格、正确公式、错误/控制
身份或人工可识别性判断。

## 构成

- 30个未见模板，六名制题人各五个；20个原创脱敏模板，10个许可明确的公开模板；
- 每模板8个错误和4个控制，共240错误、120控制；
- 六类错误各40个；每模板6个可识别单源错误和2个歧义错误；
- 60个歧义错误分为30个单源合法例外近似和30个对称多源块；
- 每模板2个普通控制和2个合法例外控制，共60+60；
- 每个错误案例由两名不接触模型的复核者独立记录唯一性和源猜测。

## 外部原始目录

```text
cases.csv
reviews.csv
third_party_declaration.json
workbooks/*.xlsx
originals/*.xlsx
```

`cases.csv`和`reviews.csv`的字段顺序由`formulaguard.v5_psl_protocol`固定。错误案例
的`source_cells`使用分号分隔的工作表限定地址。普通及单源错误必须只改变一个公式；
声明的对称多源案例必须改变2至5个公式。控制不得填写源格。

字段模板为`V5_PSL_THIRD_PARTY_CASES_TEMPLATE.csv`和
`V5_PSL_THIRD_PARTY_REVIEWS_TEMPLATE.csv`。每个可识别错误的两名复核者都必须填写
同一个唯一源；每个歧义错误的两名复核者都必须独立填写`unique_source=0`。同一案例
不得由同一复核者重复两次。所有复核者ID与全部制题人ID必须全局不相交，制题人
不得复核自己或其他制题人的案例。每模板的制题人、来源类型和许可编号必须保持一致。

声明使用`V5_PSL_THIRD_PARTY_DECLARATION_TEMPLATE.json`。除独立保管、未运行模型、
标签后释、许可/脱敏外，还必须确认全部案例已在记录的计算引擎中重算且没有显式
运行时错误、复核相互独立、制题人未兼任复核者，以及两类人员均未取得模型输出。
声明必须填写与制题人和复核者均不重合的稳定保管人ID、计算引擎及版本，并以
SHA-256绑定仓库外的许可和脱敏复核证据。

打包器只接受`.xlsx`，拒绝宏、连接、外部链接、公式格集合变化、非公式内容/可见性/
数值格式变化和声明外的公式差异。若内部求值器完整覆盖，它还验证错误确实改变至少
一个公式值；复杂语义由保管人的独立计算引擎声明兜底。打包器不生成工作簿、不运行
任何定位方法。

为降低同源泄漏，候选冻结使用的公开开发公式变换签名清单必须交给保管人；第三方
每个错误的相对公式变换哈希不得与该清单重合。PUBLIC实例ID由至少32字节的保管人
密钥做HMAC匿名化，原ID、模板和文件名映射只进入SECRET。

## 包与锁顺序

打包器不调用FormulaGuard，只验证结构、公式差异、许可声明、复核记录、唯一性、
开发变换哈希不重合和文件哈希。PUBLIC只包含`instance_id,workbook`清单、随机命名
工作簿和SECRET承诺哈希；SECRET包含标签、原表、复核与来源记录。

1. 文献门绑定当前claim matrix哈希，公开压力门从原始manifest独立重算并通过；
2. 源码、方法规格、配置和环境冻结并创建候选锁标签；
3. 保管人释放PUBLIC；
4. V5-PSL与预声明基线生成完整排名和状态并写入预测锁；
5. 保管人释放SECRET；
6. 评分器验证全部预提交哈希并只评分一次；
7. 不允许删除案例、改阈值、重新出题或根据标签创建同队列新版本。

晋级门槛以`V5_PSL_METHOD_SPEC.md`为准，所有`unsupported`案例保留在总体分母。

## 固定工具顺序

保管人在项目外运行打包器：

```bash
python scripts/build_v5_psl_third_party_pack.py \
  --raw /custodian/raw_360 \
  --output /custodian/package \
  --pseudonym-key-file /custodian/opaque_key.bin \
  --development-signatures /custodian/development_formula_change_signatures.txt
```

输出包括确定性`FormulaGuard_V5_PSL_PUBLIC_360.zip`、
`FormulaGuard_V5_PSL_SECRET_360.zip`和`package_receipt.json`。候选锁前只传递两个
归档SHA-256并写入候选锁；PUBLIC本体必须等候候选锁。PUBLIC内只有严格两列`manifest.csv`、
随机命名工作簿、逐工作簿哈希、公开元数据和SECRET预承诺。SECRET包含标签、原表、
双复核、声明、逐例验证和保管人ID映射。

开发者取得PUBLIC后运行四个固定方法：`V4-R1`、`V4.2-Review-B`、
`V4.3-Semantic-C`和`V5-PSL-dev1`。V4/V4.3固定检查Top-5，V4.2保持V4完整核心
排序并只允许可空第六位，V5-PSL按状态检查1/5/0格。每种方法都必须写入与工作簿
公式集合完全相等、名次连续且无重复的完整排名。

```bash
python scripts/run_v5_psl_predictions.py --public /released/PUBLIC \
  --candidate-lock results/v5_psl_candidate_lock.json \
  --output results/v5_psl_independent_predictions --workers 24
python scripts/verify_v5_psl_prediction_lock.py --public /released/PUBLIC \
  --candidate-lock results/v5_psl_candidate_lock.json \
  --predictions results/v5_psl_independent_predictions
```

第二条命令重新打开全部公开工作簿并复算每个分片、代码、提交、候选锁、PUBLIC和
SECRET承诺哈希；当前Git工作区必须保持候选锁提交的干净状态。只有
`prediction_lock.json`写入成功且
`secret_release_authorized=true`，保管人才可交付SECRET。

评分器先在不打开SECRET成员的情况下复算预测锁和归档总哈希，随后以排他方式写入
`scoring_started.json`，再读取标签。任何后读失败都会保留失败回执，未经保管人审计
不得换目录重跑。评分器还会解出原表，逐例复算公式差异与开发签名不重合，最后按
30个模板做固定10000次bootstrap：

```bash
python scripts/score_v5_psl_blind.py --public /released/PUBLIC \
  --candidate-lock results/v5_psl_candidate_lock.json \
  --predictions results/v5_psl_independent_predictions \
  --secret-zip /released/FormulaGuard_V5_PSL_SECRET_360.zip \
  --output results/v5_psl_independent_scored
```

评分器只写`promotion_allowed`，不会编辑源码、创建正式配置或增加Git标签。只有全部
预登记门槛为真，才可另行审计并在锁定提交上授权`V5-R1`名称。

## 当前状态

仓库只含协议、空模板和工具。六名制题人、30个模板、360份工作簿、PUBLIC/SECRET
归档、候选锁和评分回执目前均不存在；不得用工程测试替代这些证据。
