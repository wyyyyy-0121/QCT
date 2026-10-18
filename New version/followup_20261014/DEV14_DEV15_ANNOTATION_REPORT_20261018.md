# dev14–dev15：可见业务说明辅助修复实测（2026-10-18）

## 结果与采用决定

完成开发实现、完整本地运行、锁预测后分进程评分、两版各16例重放及独立审计。dev15在16个完整工作簿场景、119个已知注入错误上输出87条建议：86条正确、1条错误，精确率98.85%，覆盖率72.27%。相对dev14新增27个正确修复，同时暴露1个误修。辅助方法不替代dev11主候选；未达到双90%，目标继续active。

全部场景来自已排除最终验证的public08英国政府LCOE计算器。原件1,349个公式，仅80格具有本轮逐项核对的完整乘积说明、引用映射与单位关系：Offshore Generation 30格、CCGT Generation 25格、CCGT Carbon captured 25格。两个技术表未作为相同业务平行表投票。16副本不构成16个独立来源，80×16标签也不是独立家族证据。

| 方法 | 全部建议 | 确认正确 | 确认错误 | 未知 | 精确率确认下界 | 已知错误覆盖率 |
|---|---:|---:|---:|---:|---:|---:|
| 原论文 | 18896 | 0 | 1280 | 17616 | 0.00% | 0.00% |
| dev11主候选 | 0 | 0 | 0 | 0 | 未定义 | 0.00% |
| dev14说明辅助 | 59 | 59 | 0 | 0 | 100.00% | 49.58% |
| dev15说明辅助 | 87 | 86 | 1 | 0 | 98.85% | 72.27% |

论文输出按全部非空且不同于原式的suggested_formula计入，不按status筛选。已核对范围共1,280条建议不符合业务关系；17,616条建议超出标签范围，保留未知并进入分母。论文0%是“确认正确/全部建议”下界，不能写成整本准确率为0%。dev11零建议的精确率未定义。dev11加说明模式与说明单独模式本轮一致，分别保存。

## 实现及缺陷修复

dev14只接受完整乘积说明中的精确行标题，不猜同义词。标题须唯一、可见，单位量纲一致。候选来自论文、同行公式平移及既有单编辑生成器。用有界精确有理多项式比较加减乘关系，拒绝除法/函数/幂等超出范围表达式，不用当前数值相等代替关系证明。多个语法不同但代数等价的候选仍转复核。

dev14首轮59/119后发现：Notes只枚举model.cells，未缓存公式可能只在model.formulas中，导致参照和公式类型输入缺失。保留已锁定dev14，新增dev15将键取并集，公式文本仍来自formulas；没有降低说明、单位或候选门槛。

原件及论文源码不改。clean_original保持原始字节，其他15例用openpyxl统一另存；不声称所有Excel功能完全等价。除原件对照外，CO2 scrubbing输入设为0.25，使碳捕获错误产生非零数值偏差。输入变化、说明变化、错误注入、合法例外分别记录。各模型读取相同完整输入。

## 全场景结果与限制

| 场景 | 已知错误 | dev15正确修复 | dev15误修 |
|---|---:|---:|---:|
| annotation01 clean_original | 0 | 0 | 0 |
| annotation02 clean_input_scenario | 0 | 0 | 0 |
| annotation03 isolated_operator | 1 | 1 | 0 |
| annotation04 isolated_reference | 1 | 1 | 0 |
| annotation05 isolated_coefficient | 1 | 1 | 0 |
| annotation06 common_operator_row | 30 | 30 | 0 |
| annotation07 common_coefficient_row | 25 | 25 | 0 |
| annotation08 common_reference_row | 25 | 25 | 0 |
| annotation09 multiple_regions | 3 | 3 | 0 |
| annotation10 missing_note | 1 | 0 | 0 |
| annotation11 hidden_note | 1 | 0 | 0 |
| annotation12 duplicate_caption | 1 | 0 | 0 |
| annotation13 documented_exception | 0 | 0 | 0 |
| annotation14 wrong_note_clean | 0 | 0 | 0 |
| annotation15 wrong_note_polluted_peers | 29 | 0 | 1 |
| annotation16 wrong_note_with_error | 1 | 0 | 0 |

漏修33格：缺说明、隐藏说明、重复标题各1格；错误说明使29个污染公式符合错误关系；另1格错误说明与孤立错误没有合格候选。全部保留于分母。核对范围以外不默认原表正确。

唯一误修在annotation15的Offshore LCOE!O27：正确原式为 =$D$11*O25*O26*$D$14。说明的Gross load factor被换成同为百分比的Net efficiency (LHV)，同行另29格共同污染，方法建议 =$D$11*$D$12*O26*$D$14，把正确发电量5,326,080改成8,322,000。单位一致、完整标题映射、大量参照一致均不能证明说明可信；该反例阻止自动采用。

原表Carbon emissions说明写Fuel consumption，公式实际经Therm换算后乘kgCO2/Therm。精确说明映射得到MWh，量纲不合，故拒绝。货币缩放等不完整说明也保留不支持，不能为扩大覆盖率放宽这些检查。

## 验证与资源

- 155项测试通过，含缓存/无缓存预测一致性、公式输入绑定、大整数、隐藏/重复/错误说明反例。
- 两版各16例完整重放一致。独立token栈解析审计分别核对59/87条说明建议的关系、说明内容、参照平移，评分计数全部一致。
- dev14首版独立审计误写openpyxl token类型为缩写，首次运行断言失败且未生成成功结论。保留原脚本，v2改为OPERATOR-INFIX/PREFIX，通过算术反例自测后完成审计；未改冻结模型或预测。
- 167例旧开发输入的dev15增量检查保持dev11全部行输出不变，没有新增说明建议。该检查复用冻结上游SG/FG，没有重跑167例完整检测；旧输入均无完整说明证据。
- 原件SHA-256：b0f15382e8c9c9b74d944a0ab8301a3326fb3bfbf4a950896a66f29c52000357。
- dev14完整16例wall 20.580秒、CPU 20.574秒；dev15 wall 20.513秒、CPU 20.512秒。每版21,584个公式格，峰值RSS约329.6MiB，未用GPU。重放另计。
- dev14预测锁：bcb648924223c9a144d8aeff5c0de8f8e3d572e123194ec2c68e2536438ac103。
- dev15预测锁：ef0df7aa6b6a040eed9d9bb596ef984ba8c0b04b6589659e2aed4a64e00d1121。

预测前锁源码、测试、计划、输入、索引；答案及准备/oracle代码的读取阻断已实际测试。预测完成后另进程用Python AST及精确SymPy有理数核对，独立审计另用openpyxl token栈。数值审计仅为给定上游输入的局部关系检查，不是全表重算或专家认证。

数据及预测：development/annotation_dev14_inputs_v1/、annotation_dev14_v1/、annotation_dev15_v1/。
审计：qa/ANNOTATION_DEV14_INDEPENDENT_AUDIT_V2_20261018.json、ANNOTATION_DEV15_INDEPENDENT_AUDIT_20261018.json、ANNOTATION_DEV15_LEGACY_REGRESSION_20261018.json。

## 后续开发

先研究说明来源、适用范围的独立核对和可执行业务约束交叉验证，不能用自身说明或多数公式自行证明可信。在已排除来源中增加不同领域、业务可核查的完整工作簿，保留合法例外、错误说明和不支持输入。保留主候选对照，解决33个漏修的证据缺口和1个误修，不按有利场景选择性汇报。

最终合格公开来源/独立模板家族仍0。本轮未下载预留最终来源的工作簿正文；模型、评分、纳入规则冻结后才进入最终验证。三类最终验证分别达到90%/90%的目标不变。
