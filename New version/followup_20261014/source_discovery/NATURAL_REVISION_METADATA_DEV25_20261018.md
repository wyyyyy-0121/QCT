# dev25期间的自然错误版本谱系预查

从此前`metadata_v3/RECEIPT.json`的提交搜索结果选取6个独立仓库，固定commit和其唯一parent，读取Git commit/tree元数据共24次成功响应。没有下载工作簿blob、补丁或逐格答案。保存过滤后的树/父提交字段与各文件SHA；提交说明未用作正确公式标签。合格最终来源/家族及已核验自然真值对继续为0。

|候选仓库|修订前/后工作簿数|元数据发现|自然错误配对状态|
|---|---:|---|---|
|mightyoung/software-cost-calculator|0/0|两版均没有所查四种工作簿扩展名|无工作簿对|
|zbynekdrlik/vyuctovanie|0/0|两版均没有所查四种工作簿扩展名|无工作簿对|
|reckak/statistics-for-psychology|5/6|新增kapitola_06.xlsx，已有同路径blob不变|新增文件不能证明错误原表/修订对|
|Pradeepgdeepu/Data_Cleaning_with_excel|0/1|新增xlsm，parent无工作簿|无同路径原表|
|alvenyuka/Stock-Portfolio-Tracker-Analytics-Engine|1/1|工作簿blob未变|提交命中不代表修改了工作簿|
|OpenSourceRisk/QuantLibAddIn|578/581|新增4路径、删除1路径，既有同路径blob未变|可能重命名或新增示例，未建立修复配对|

扩展名范围为xlsx/xlsm/xls/ods，树均未截断。零个“同路径工作簿blob发生变化”只适用于这6个固定修订，不能推断整个仓库历史没有自然错误，也不排除跨路径重命名。QuantLib的测试/示例性质、谱系与许可证也未审定，不能据581个文件计独立模板或来源。搜索命中数和仓库数均不计合格来源。

另对RR原表的Dropbox `dl=1`、dl.dropboxusercontent入口和已固定scienceetonnante镜像执行3次HEAD，均超时，读取正文0字节。未取到原表/可靠修订配对；Dropbox、作者机构和镜像仍属同一个历史案例，不重复计源。

证据分别在`natural_commit_trees_dev25_20261018/RECEIPT.json`及`rr_original_headers_dev25_20261018/RECEIPT.json`。这些目录不是数据验收结果。下一步应继续寻找有前后工作簿和可信修订说明的记录；当前已冻结的模型进程未读取这些来源文件。既有6大学、Excel Easy、NSW等注入候选及其最终冻结/获取约束保持。
