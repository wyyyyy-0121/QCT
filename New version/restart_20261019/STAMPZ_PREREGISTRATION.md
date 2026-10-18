# StampZ 绘图模板：自然错误候选开发审计

来源 `Stainlessbrown/StampZ-III-Binary` 全部排除最终验证；提交说明已经被阅读。版本链元数据已固定在 `source_evidence/STAMPZ_LINEAGE.json`。原版parent为 `5e2d7a350066832ec49c784317b7655fd1b05b68`、blob为 `a0061f2d21ba782736ed3d7c5c5939ac619cfdf3`；修订commit为 `c929f4427fb14c480b1239780225838a6d626329`、blob为 `85bbe870e31390d4c57ea0ed6236fe8caadb6cca`。路径 `data/templates/plot3d/Plot3D_Template.ods`。

先取得原版，校验Git blob及SHA-256。论文仅支持xlsx输入，因此用隔离LibreOffice无UI转换副本；保留原ODS哈希、转换器版本、日志与xlsx哈希。对转换副本运行冻结论文/dev11只读推理；完整预测或失败先锁定，才允许获取修订ODS。转换不等于原生ODS支持，后续若无法核对公式/输入保真，本案例不得计模型准确率。

修订取得后用ODS XML按表、行、列展开库存，核对公式、数值、文字和布局；不从提交说明或版本差异直接生成真值。若是非公式、非静默错误、生成样例或业务含义无法证明，则拒绝自然修复标签。许可未确立，原件、转换件与含第三方内容的差异保留本地git忽略；仅上传取得回执、哈希和资格结论。模型与阈值不调整。
