# 自然错误与来源谱系预查补充

v9/v10只取得公开目录、Git树/ref、README和论文入口元数据，没有下载候选工作簿，也没有读取逐格修复答案。请求失败如实保留；这些证据不增加最终来源或模板家族数。

Reinhart–Rogoff复现仓库README明确链接所谓Original data：`https://www.dropbox.com/s/aw3yb8u2mvr599p/Reinhart%20and%20Rogoff.xlsx?dl=0`。该地址尚未访问，不能证明仍可下载、包含错误公式，或已取得原表/修订配对。HAP、scienceetonnante及其他RR镜像都属于同一个历史案例，不能按仓库数重复计源。

本轮Git ref响应明确返回object.type=commit，因此现在可以固定HAP main提交 `b9c34472da97465050780dae5a4dab9ab7c69a63` 和scienceetonnante master提交 `658bfafcfe19878cf13ffa748d3e5ab8c1969f6b`。这补足上轮仅凭树端点无法确认commit类型的证据，不证明工作簿真值。原始响应保存在v9的rr_hap_ref.source和rr_science_ref.source。

作者网站data目录响应成功，主题入口与PERI迁移入口仍需继续查证；猜测旧路径404、Harvard/OUP访问拒绝和AEA超时没有产生自然错误真值。vincentarelbundock和McGinn仓库树只有处理后CSV，不作为原始错误公式工作簿。CORE个人课程复现也不自动获得自然错误标签。

六个大学目录的字面链接谱系检查确认Tennessee–Kentucky烟草预算明确联合，不能重复计源。跨站导航到已排除的Iowa目录不能单凭链接证明工作簿同源，也不能忽略后续模板核查。报告不声称通过工作簿内容验证了独立性。

新增审计 `scripts/audit_source_metadata_v9_v10.py` 核对这两批索引及保存响应的字节数/哈希，并检查常见凭据模式；失败响应同样保留。原有v2–v8审计不修改。
