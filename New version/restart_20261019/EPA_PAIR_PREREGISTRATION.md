# EPA历史版本对：开发取证预登记

本次只研究EPA官方成本计算工作簿。整个EPA来源已阅读勘误，永久排除最终验证。Flares和Oxidizers即使都认证，也按一个机构来源计数，不伪装成两个独立来源。

官方当前页面：`https://www.epa.gov/economic-and-cost-analysis-air-pollution-regulations/cost-reports-and-guidance-air-pollution`。官方2021快照：`https://19january2021snapshot.epa.gov/economic-and-cost-analysis-air-pollution-regulations/cost-reports-and-guidance-air-pollution_.html`。

原版候选为快照页直接链接的2019年Flares与2018年Oxidizers文件；修订候选为当前页面直接链接的2022年Flares与2024年Oxidizers文件。先保存原件、HTTP回执与SHA-256，再用既有只读入口运行论文原模型和dev11。xlsm按OOXML读取，不运行VBA；这不证明宏依赖行为得到支持。没有预先证实的平行表关系，不传平行表参数。

批次使用既有8进程运行器，每个工作簿单独进程、超时300秒。仅有两个工作簿时最多两个进程有任务。完整预测或运行失败及全部输入先锁哈希，再允许取得修订件；预测失败也保留，禁止改模型后重试冒称预揭示结果。

修订件取得后先对地址、表结构、公式、常量、隐藏内容和宏依赖做审计。版本相隔多年，不能假定逐格可比较。勘误及修订公式不是独立的逐格真值，需要结合表内角色、输入、公式定义及官方手册验证；无法证实的格保留unknown。没有认证前不评分，不计来源准入数。

原件及含第三方内容的差异均留本地，上传哈希、获取回执、运行资源和资格结论。美国联邦机构出处不自动覆盖工作簿内第三方内容，暂不分发工作簿。
