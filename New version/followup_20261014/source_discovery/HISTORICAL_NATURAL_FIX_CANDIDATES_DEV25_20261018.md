# 从历史修订找到5个有前后工作簿的自然错误候选

4次GitHub提交搜索按`committer-date:<2024-01-01`限定较早记录；随后对5个候选执行20次Git commit/tree元数据请求，全部成功。同路径工作簿blob实际变化共7处，前后commit、parent、tree、blob SHA及大小均已保存并独立重建核对。没有下载工作簿正文或补丁，没有把提交说明直接当正确公式标签。

|仓库与固定修订|同路径变化的工作簿|当前证据边界|
|---|---|---|
|[ECB2020/Hobyah](https://github.com/ECB2020/Hobyah/commit/a6c7cd441ff1aca4915e8bc2b61d719643927cac)|slug-flow-quadratics.ods、slug-flow-quadratics.xlsx|说明披露错误单元格位置与错误机制；该来源保守排除未见最终验证，可用于后续开发。作者称ods为主版，两格式不算两个家族|
|[CASPER-Baylor/VDRIAD](https://github.com/CASPER-Baylor/VDRIAD/commit/220061c408beb0b2b9c7d686d4431a36e1d7bc56)|data/Couedel_PhysRevE_105_015210_fig08_sheathHeight.xlsx|说明称更正表与脚本；也可能只改实验数据，不能据blob变化认定公式修复|
|[mirontoli/cv-500](https://github.com/mirontoli/cv-500/commit/48a359e080afb4d793994be3da225d509a683b73)|data/500samah-values.xlsx|提交标题明确称修复Excel错误公式；仍需逐格差异和业务依据核对|
|[Gh0st0ne/LDAS](https://github.com/Gh0st0ne/LDAS/commit/f15063f13cbbaab00cd77414a11a1e8f8a6756ed)|docs/templates/template_taini_worksheet_laser.xlsx|搜索命中公式修复，文件明显改变；可能混有布局/内容变化，不能把全部差异都标错|
|[New-College-of-Florida/Planned-Parenthood-Drug-Inventory](https://github.com/New-College-of-Florida/Planned-Parenthood-Drug-Inventory/commit/d7f90d19dc8dd65e3fd352acee7406453af413a3)|data/20141021/Purchase Log.xls、data/init/manager.xls|说明涉及XLS公式问题；需辨别公式错误值、业务静默错误和工具兼容修复，旧xls也需保留兼容性分母|

以上是自然错误取证候选记录，不是5个合格最终来源或7个独立模板。许可证、来源间谱系、历史测试集重叠、完整原始/修订文件获取、公式级差异、修订的业务正确性及支持格式均未验收。修复后文件存在不等于每个原公式都错误，也不证明修订后全表无错。

补充信息暴露记录：在复核完整搜索命中说明时，Hobyah提交文本明确披露J13/J14及车体面积错用的机制；这已是部分错误位置/原因信息，不能继续声称该来源答案从未暴露。虽未取得任何前后工作簿正文，也未将说明输入dev25模型，仍将ECB2020/Hobyah整个来源保守排除未见最终验证，后续可作为公开自然错误开发案例。其他候选也不能仅因正文未取就声称答案绝对未见，进入最终清单前需检查已记录提交文本的披露程度。此处不把披露位置直接认证成完整逐格真值。

搜索只读每个查询的第一页，不能据总命中数声称全面查全。其中`"formula error" "xls"`响应标记`incomplete_results=true`；保留该标记和原始失败审计日志。初版审计错误地要求搜索完整，后来改为核对已固定命中的谱系，同时显式记录搜索不完整。这不影响5个固定提交和20份Git树/提交证据的独立验证，但不支持总体数量推断。

资料目录：`historical_fix_search_dev25_20261018/`与`historical_fix_lineage_dev25_20261018/`；独立审计为`../qa/NESTED_CALIBRATION_DEV25_HISTORICAL_METADATA_AUDIT_20261018.json`。此前6个无同路径变化的候选、RR超时证据保留，不以本轮结果改写历史记录。

后续优先将Hobyah按已排除来源做自然错误开发取证；cv-500等其余候选先核对修订依据和许可证，再按最终模型/数据隔离协议固定获取阶段。需要逐格查看最终答案的作者审计必须与模型开发分离。CASPER须先证明改的是公式；药品库存须先区分非静默错误；同源格式和复制版本整体去重。当前所有新候选尚未进入模型进程，合格最终来源/家族与已核验自然真值对仍为0。
