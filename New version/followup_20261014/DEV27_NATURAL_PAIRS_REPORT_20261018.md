# dev27：核验出505个真实自然公式错误，原论文与dev11全部漏修

本轮完成LDAS和cv-500两个固定自然修订候选的原表推理、预测锁定、重放及独立公式/语义核验。cv-500建立第一组可靠的自然公式错误开发配对：505行的词义字段错误指向下一行，实际505个渲染结果均不符本行记录，修订只改这505个引用。原论文0.3.0与dev11均0建议，精确率N/A、正确修复覆盖0/505=0%。这没有性能提升，却明确了真实跨域缺口。

两来源均在获取工作簿前登记为开发并整体排除最终未见验证。此前阅读cv-500来源README已暴露错误机制，LDAS提交说明已披露空白箱机制，不能算最终新来源。最终合格来源/家族仍0/0；自然错误开发真值对由0增加为1，不能把505同源行算505家族。

## cv-500逐格真值

固定parent`562e569eae04263ca01ef41c109c2a8b98a1c7ff`、修订`48a359e080afb4d793994be3da225d509a683b73`，原始与修订工作簿Git blob及SHA均通过。原表只有Sheet1，505个E列公式；其他单元格内容未变。原表E1的CONCATENATE组合A1标题、B1发音、C2词义、D1描述，修订把C2改为C1；同样偏移贯穿E1:E505，末行引用空白C506。来源data/README定义每行为一条词条，并记录对应字段含义与本行公式，支持同一记录的业务依据。

独立有限字符串解释器逐字解析Excel引号、转义双引号和引用，不使用论文求值器；逐行检查旧引用序列A_r/A_r/A_r/B_r/C_(r+1)/D_r，新序列只把C改为r。使用四个本行字段单独构造预期HTML，全部505个修订结果精确匹配；原始505个实际渲染均不同。另用CURRENT/NEXT行词义反事实标记验证依赖方向，反事实不作为新增自然错误样本。独立验证器用另一套引号隔离/引用替换核对每条自然正解，避免只由同一解释器自证。

openpyxl库存与独立OOXML公式解析一致；全部原始公式格有标签，没有将未知区域假定正确。原表没有列标题，来源README为作者评分依据，未传给模型；两模型只读原表，使用相同信息，不能声称它们获得了README合同。旧版全部公式模式一致，原论文505行都low_risk，dev11全部abstain。这支持研究系统性同向错引用及文本语义兼容性，不能据旧版列内一致性断言正确。

原论文/主候选推理wall0.490秒、CPU0.490秒、峰值55,672 KiB，505格。推理子进程未读取修订表、来源说明或答案，先锁预测后评分；独立重放完整输出一致。没有按本次答案更改模型或选择阈值。

## LDAS不能强行标成公式错误集

LDAS原表299个公式，修订仍299个，同地址334处公式变化和435处值变化。两模型都0建议，原始输出重放一致。原表命名范围NBOXES、LBOX1…4指向输入；原C10箱号缺失，修订补1，导致旧第一箱72个计数偏小。这是输入遗漏，不能冒充72个错误公式。

独立AST受限解释器仅执行实际计数所需的加减乘、SUM、IF、名称和引用，576个前后缓存试次值逐格匹配。缓存只核验执行数值，不当业务真值。对4个箱全部15种非空启用掩码，用独立累计试次规则检验；原表注释明确规定空箱位于最右侧，在4种符合声明的掩码下，补全缺失C10后两版公式都正确。其余11种掩码属于原声明之外，修订只修好其中部分，前部空箱时仍有计数偏移，不能把修订全表当所有条件下的oracle。

工作簿原始SUBJECT输入均为句点占位，而注释要求正数；不能把模板占位当已经通过实际实验输入校验。反事实不修改raw原件，也不计自然错误个数。此候选没有建立可靠自然公式错误标签，因此本次精确率/覆盖均N/A。独立核验保存全部15掩码结果，包括修订仍失败的情况。

## 取得、复现与许可边界

工作簿原始二进制都留本地raw并git忽略。LDAS BSD 2-Clause声明已保存；cv-500固定树未见许可证，因此不声称开放再分发权，也不上传包含完整词库正文的author_diff压缩文件，保留SHA与重建入口。本次上传公式证据、预测、取得凭证、语义核验和报告。cv-500首次修订blob传输不完整，首次推理因获取未完成而未启动；保留两份失败日志，重取同一blob并核对后再启动第一次实际预测，没有换版本。

原表共有804公式格，两个案例的推理/重放和独立OOXML均通过；`qa/NATURAL_PAIRS_DEV27_VERIFICATION_20261018.json`记录检查结果。每个具体来源只有一次输入原表，复制掩码不增加自然样本数。

```bash
/home/ayaka/hybridguard/.venv/bin/python qa/run_ldas_natural_dev27.py predict
/home/ayaka/hybridguard/.venv/bin/python qa/run_ldas_natural_dev27.py replay
/home/ayaka/hybridguard/.venv/bin/python qa/diff_ldas_natural_dev27.py
/home/ayaka/hybridguard/.venv/bin/python qa/audit_ldas_trial_semantics_dev27.py
/home/ayaka/hybridguard/.venv/bin/python qa/run_cv500_natural_dev27.py predict
/home/ayaka/hybridguard/.venv/bin/python qa/run_cv500_natural_dev27.py replay
/home/ayaka/hybridguard/.venv/bin/python qa/diff_cv500_natural_dev27.py
/home/ayaka/hybridguard/.venv/bin/python qa/certify_cv500_natural_dev27.py
/home/ayaka/hybridguard/.venv/bin/python qa/verify_natural_pairs_dev27.py
```

先用已提交acquire脚本从固定blob取得原件，若转移失败按保存恢复凭证重试同blob；已有输出拒绝覆盖，完整重建在隔离副本。LDAS/cv-500薄包装复用dev26只读worker和OOXML审计，所以部分内部日志文字仍写DEV26；目录、原表路径、来源锁、preregistration和上游SHA分别绑定当前实验，未把旧结果当新推理。

下一步开发与本次发现相符的文本公式完整解析、类型与引用来源追踪，再研究明确可见记录规则下的候选修复；先有真实业务依据，不能只把所有跨行引用改为同一行。合法跨行、相邻记录关联、偏移字段、HTML与非HTML文本都必须留反例。无充分业务意图时继续复核，不把README逐格正解当检测输入。新方法须在来源隔离开发对照与完整旧回归上验证；尚无主候选改动，双90%目标仍active。
