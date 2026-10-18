# dev26：实际运行自然修订候选原表，发现指定前后版本不能证明所称错误

已取得Hobyah固定parent与修订的xlsx/ods各两份，逐份验证Git blob与SHA-256。先对原xlsx运行原论文0.3.0和dev11并锁预测，之后才解析修订版本与公式差异。199个原始公式格，两模型均0建议，原表预测重放一致。随后发现两处所称错误在固定旧版中已经使用相应车辆面积，不能按提交说明制造错误标签；本次精确率N/A，覆盖率也N/A。

来源在预查时已经因提交说明暴露位置/机制而整体排除未见最终验证。此次是公开自然错误候选的开发取证，不计最终6来源/15家族。没有新模型、没有修改原表，也没有性能提升结论。

## 实际运行与输入隔离

预登记`HOBYAH_NATURAL_DEV26_PREREGISTRATION_20261018.md`在工作簿取得前单独提交。parent为`7fd04102210d9d830ff23b497b8ce20f8e5dc215`，修订为`a6c7cd441ff1aca4915e8bc2b61d719643927cac`。LICENSE为BSD 2-Clause；工作簿内也有licence表，版权保留。原始四文件本地放在`development/natural_hobyah_dev26_v1/raw/`，git忽略，不上传第三方二进制。取得凭证保存URL、Git blob、SHA和超时。

原论文适配器及dev2→dev4→dev6→dev11选择流程参数不变；没有独立平行表声明，parallel_sheets为空。子进程拒绝修订文件、修订说明、truth/label/score等文件，实际只读before.xlsx；源码与输入哈希锁定后保存全部输出。原表含早期版本说明和一条blockage定义注释，保留为可见输入；未据此声称全表从未出现任何历史修订文字，原表注释扫描未出现本次J13/J14位置说明。全研究作者此前看到提交元数据的暴露仍如实记录，子进程隔离不抹除此事实。

一次完整推理wall0.391秒、CPU0.390秒，峰值50,380 KiB，GPU未用。规模只有199公式格，因此短时低占用符合实际工作量。原论文和dev11均0建议；保存全部行、状态及输入公式，没有只输出被选中的成功行。独立重放两种模型输出一致。

## 为什么不能标成“两处漏修”

修订说明称LCV/HGV项错误使用car area，但前后表布局大幅变化，旧版对应L13/L14，新版才是J13/J14。旧版199个公式，新版202个公式；按同地址比较出现398处公式变化及754处全部非空值变化。这不是398个错误。

|可见业务角色|固定旧版|固定新版|核对|
|---|---|---|---|
|LCV项|L13，面积H20|J13，面积F20|H20/F20均由可见LCV area标签确认|
|HGV项|L14，面积H22|J14，面积F22|H22/F22均由可见HGV area标签确认|
|car面积|H18|F18|两项旧公式的blockage分母均未使用car面积|

按已核对的可见角色映射，将旧版H/F车辆参数、C/B隧道参数、L/J密度项归一后，两处前后公式逐字符一致。作者指定ods为主版本，因此又取得同两提交的ods，直接解析content.xml，按重复行/列位置定位；其两处公式与xlsx一致，也已使用对应车辆面积。这只能确认这两个固定前后版本不能证明提交文字所称的修复，不推断仓库全历史无自然错误，也不证明整个原表正确。

公式库存用openpyxl和独立OOXML解析交叉检查。首版审计遇到共享公式时主动报错，保留失败日志；随后用独立结构公式平移器展开OOXML shared master，199/202个公式与openpyxl完全相同。没有通过跳过共享公式来使审计通过。角色核对又用ODS公式独立交叉检验。

没有可靠已标错误，覆盖分母未建立，不能把0条建议说成0%错误覆盖或100%安全。两处位置不被强行标错，其他建议也没有被假定正确；本次不生成准确率评分。后续如查到真正有错的更早版本，必须单独登记并保留这次无效配对证据。

## 凭证与下一步

主目录`development/natural_hobyah_dev26_v1/`保存取得凭证、source_lock、prediction_lock、全部预测、replay、author_diff与role_alignment_audit；最终核验`qa/HOBYAH_NATURAL_DEV26_VERIFICATION_20261018.json`。dev25历史锁仍保留，论文源码未改。

```bash
/home/ayaka/hybridguard/.venv/bin/python qa/run_hobyah_natural_dev26.py predict
/home/ayaka/hybridguard/.venv/bin/python qa/run_hobyah_natural_dev26.py replay
/home/ayaka/hybridguard/.venv/bin/python qa/diff_hobyah_natural_dev26.py
/home/ayaka/hybridguard/.venv/bin/python qa/acquire_hobyah_odf_dev26.py
/home/ayaka/hybridguard/.venv/bin/python qa/audit_hobyah_role_alignment_dev26.py
/home/ayaka/hybridguard/.venv/bin/python qa/verify_hobyah_natural_dev26.py
```

已有输出拒绝覆盖。首次raw下载前后xlsx均超时，保留初次凭证后改用相同Git blob API取得并校验；LICENSE同样从固定blob回退成功。恢复取得的URL、哈希和原始失败均记录，不用不同文件替换失败目标。

下一步继续cv-500、LDAS等固定修订的可靠原表/修订对取证，优先确认公式级错误确实存在且有可见业务依据；Hobyah可继续追溯更早历史作为已排除开发来源。最终合格来源/家族和自然真值对仍0，三类独立双90%目标active。当前主候选dev11开发指标仍99.7960%精确率、78.4817%覆盖，不能把本次无标签原表加入该分数。
