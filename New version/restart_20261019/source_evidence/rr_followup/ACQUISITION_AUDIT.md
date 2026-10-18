# R&R / HAP 复现包获取与来源资格审计

审计时间：2026-10-18 UTC。结论：开发期来源线索，非最终验证数据。

## 获取记录

- 来源页面：UMass PERI HAP 工作论文页面；页面链接到更新日期为2013-05-17的代码/数据包。
- 实际获取：`https://peri.umass.edu/images/WP322HAP-RR-GITD-code-2013-05-17.zip`，HTTP重定向后返回ZIP，大小632,057字节。
- 本地忽略目录：`source_evidence/rr_followup/private/`。原始ZIP及提取文件不进入Git。
- ZIP SHA-256：`93900259e271c96f654bb61a2808f7eeb12320103a3fb092ee239859ee23d95c`。
- 包含`RR.xls`、`RR-keycolumns.xlsx`、各国CSV压缩包、HAP R代码及Stata数据；不含名为原始错误版本/修订版本的成对工作簿，也没有独立许可证文件。
- `RR.R`头部写明“this code and the related data are open-source under the BSD 2-clause license”。这支持代码及相关数据包的开放许可声明，但未逐文件核实原始RR工作簿或再分发权；本地不发布工作簿。
- `RR.xls`的OLE属性标记Author为Carmen Reinhart、Last Saved By为Michael Ash、创建时间2009-11-22、保存时间2013-05-17；该属性是可核线索，不能单独证明版本的错误状态或真值。
- `RR.xls`经LibreOffice转换副本后，openpyxl看到20个工作表、3,637个公式。数量仅描述转换副本，不视为原始BIFF公式保真认证；原件哈希保持不变。

## 错误证据与边界

HAP公开R代码称“Spreadsheet error”，在构造`RR.spreadsheet`分析时排除Australia、Austria、Belgium、Canada、Denmark五国。PERI页面的论文更正说明也记载初始表述遗漏Belgium。这是对已发表分析受到电子表格问题影响的独立出处证据。

但该证据并未把问题映射到`RR.xls`中的特定公式单元格，也没有给出同一工作簿的纠正公式版本。HAP的`RR-keycolumns.xlsx`是代码生成的派生输出，不是RR.xls的修订版。故不能把五国或相应公式直接标作可评分错误格，也不能计算HybridGuard准确率/覆盖率。即使已下载的工作簿里观察到公式，仍须确定问题究竟是公式错误、范围/筛选错误、分析纳入规则还是流程控制错误，才能判断是否符合静默公式错误定义。

## 时间线和状态

归档的Carmen Reinhart `41_data.xlsx`请求和Dropbox `Reinhart and Rogoff.xlsx`请求本次仍超时。PERI复现包与RR.xls可访问，但未解决原始错误表/修订表的对应关系。因此该R&R案例被整体标记为已揭示开发证据；不得再预留作盲测。下一步仅继续寻找未揭示的来源，并保留R&R为来源资格/错误机制研究候选。
