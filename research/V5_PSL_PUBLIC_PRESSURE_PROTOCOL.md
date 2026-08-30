# V5-PSL 公开开发压力协议

## 证据边界

本阶段只使用已揭晓的公开或历史语料开发`V5-PSL-dev1`，不能产生独立、盲测或
`V5-R1`结论。原始语料保存在`data/external/v5_psl/raw/`或仓库外，不提交、不由本
项目再分发。六个来源、固定哈希、固定提交和许可状态以
`data/external/v5_psl/corpus_registry.json`为准。

四个定位语料是Modified EUSES、Info1、Integer Corpus和Enron Error Corpus。
FoRepBench只做618项公式修复角色审计；SpreadsheetBench只做完整工作簿清点、解析
记账和无标签安全诊断，不产生定位准确率事件。

## 固定顺序

1. 人工复核每个来源的许可和使用条款，再显式传入`--accept-terms`下载固定版本。
2. 为六个语料分别生成`inventory.csv`和`inventory_audit.json`。
3. 人工完成公开压力manifest中的转换、源格映射、控制和排除理由。
4. 对FoRepBench和SpreadsheetBench生成独立角色审计。
5. 同时运行默认方法和四项预声明消融，生成逐例完整排名。
6. 使用原始manifest独立重开全部工作簿，重算分片、事件和开发变换签名。
7. 硬门通过后才能生成文献门回执和开发候选锁。

不得从消融结果选择阈值。公开压力失败后最多允许一次有根因、证据哈希和源码提交
记录的机制修订；第二次失败即停止，不读取第三方确认集。

## 命令

先验证注册表，再按语料逐个下载和清点：

```bash
python scripts/prepare_v5_psl_public_corpora.py show --json
python scripts/prepare_v5_psl_public_corpora.py download \
  --corpus info1 --root data/external/v5_psl/raw --accept-terms
python scripts/prepare_v5_psl_public_corpora.py adapt \
  --corpus info1 \
  --source data/external/v5_psl/raw/info1/extracted \
  --output results/v5_psl_inventories/info1
```

六个语料均须执行等价的`adapt`。补充角色审计为：

```bash
python scripts/audit_v5_psl_supplemental_corpora.py \
  --registry data/external/v5_psl/corpus_registry.json \
  --corpus forepbench --source /path/to/FoRepBench \
  --output results/v5_psl_roles/forepbench
python scripts/audit_v5_psl_supplemental_corpora.py \
  --registry data/external/v5_psl/corpus_registry.json \
  --corpus spreadsheetbench --source /path/to/SpreadsheetBench \
  --diagnose-limit 25 --output results/v5_psl_roles/spreadsheetbench
```

正式SpreadsheetBench角色审计不得传`--limit`，并须成功诊断最多25个可解析且含公式
的工作簿。随后运行并独立审计公开压力：

```bash
python scripts/run_v5_psl_public_pressure.py \
  --manifest /path/to/public_pressure_manifest.csv \
  --output results/v5_psl_public_pressure --workers 24
python scripts/audit_v5_psl_public_pressure.py \
  --registry data/external/v5_psl/corpus_registry.json \
  --inventory-audits results/v5_psl_inventories/*/inventory_audit.json \
  --role-audits results/v5_psl_roles/*/role_audit.json \
  --manifest /path/to/public_pressure_manifest.csv \
  --run results/v5_psl_public_pressure \
  --revision-log research/V5_PSL_MECHANISM_REVISION_LOG.json \
  --output results/v5_psl_public_pressure_audit.json
```

审计器要求运行目录文件集合精确匹配协议，逐个重算完整排名和`1/5/0`行动预算，
从manifest与分片重建事件CSV，并从原始/错误工作簿对重建开发公式变换签名。

## 候选锁前检查

`research/V5_PSL_LITERATURE_GATE_TEMPLATE.json`的`claim_matrix_sha256`必须等于当前
`research/V5_PSL_CLAIM_MATRIX.md`的SHA-256。六个预登记研究方向必须各有一条完整的
主文献核对记录，包含稳定链接、核对日期、重叠判断、允许主张和外部核对笔记哈希；
只有`unresolved_claims=[]`后才能设置`passed=true`。正式公开压力从干净Git提交启动，
每个纳入案例必须有可复核原表；压力审计、候选锁和当前提交的源码清单必须逐项一致。
候选冻结还要求公开压力签名文件哈希与审计回执一致，并能执行
`libreoffice --version`。独立保管人须在冻结前只提供PUBLIC与SECRET归档SHA-256，
冻结命令必须把两者写入候选锁，不能在锁后替换第三方案例。

候选锁只授权`V5-PSL-dev1`进入第三方确认流程，不授权正式版本名。
