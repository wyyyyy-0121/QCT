# FormulaGuard model-discovery Gate 1 方法卡

日期：2026-08-31
状态：完成；方法身份和指标兼容性已固定

## 总则

`official_current_implementation`、`validated_reimplementation`、
`idea_level_proxy` 和 `related_work_only` 不可互换。没有共同输入、输出和
指标的方法不进入“超过学术基线”的数字比较。Gate 1 不授权新模型实现。

## 1. ExceLint

- 方法身份：`official_current_implementation`
- 实现状态：`linux_cli_verified`
- 引用：Barowy, Berger, Zorn, OOPSLA 2018, DOI 10.1145/3276518
- 原文入口：https://www.microsoft.com/en-us/research/publication/excelint-automatically-finding-spreadsheet-formula-errors/
- 任务：oracle-free static formula anomaly detection and ranked review
- 推理需要真值：`false`
- 输入：formula references; cell layout; formatting and values as supported by the implementation
- 输出：relative-reference fingerprints; homogeneous rectangular regions; suspicious cells; proposed fixes; entropy-based scores
- 原生指标：anomalous-cell/region detection; review ranking; candidate-fix evaluation
- 可兼容指标：region_hit; fixed-review action cost
- 不可混用：source-cell MRR when the implementation only emits regions; repair exactness without a shared repair oracle
- 允许主张：official current ExceLint implementation was built and its native region/fix output can be compared where inputs are supported
- 禁止主张：this run reproduces the OOPSLA experiment or proves superiority over the original paper implementation

### ExceLint 运行记录

- 构建：`npm ci --ignore-scripts; npm run build`
- Node：`v22.22.1`
- 样例：test/act3_lab23_posey.xlsx; FormulaGuard:data/propagationbench_full/clean/attendance_v0.xlsx; FormulaGuard:data/external/enron/workbooks/converted/22.xlsx
- 重复运行一致：`true`
- 输出边界：JSON WorkbookAnalysis with sheets, proposed fixes and foundBugs; not a complete per-formula ranking

## 2. CUSTODES

- 方法身份：`related_work_only`
- 实现状态：`no_public_official_runner_located`
- 引用：Li et al., ICSE 2016
- 原文入口：https://sqlab-sustech.github.io/files/paper/ICSE2016.pdf
- 任务：unsupervised spreadsheet cell clustering and formula smell detection
- 推理需要真值：`false`
- 输入：formula AST; reference relations; labels; layout; spatial relations; fonts; fill colors
- 输出：two-stage clusters; minority/outlier cells; smell categories
- 原生指标：clustering quality; smell detection
- 可兼容指标：region_hit only after an explicit cell/region mapping
- 不可混用：source MRR without a documented mapping
- 允许主张：CUSTODES establishes AST/reference-based role clustering and static outlier detection
- 禁止主张：FormulaGuard has reproduced or exceeded CUSTODES without a validated implementation

## 3. WARDER

- 方法身份：`related_work_only`
- 实现状态：`no_public_official_runner_located`
- 引用：Da Li et al., WARDER, QRS 2019, DOI 10.1109/QRS.2019.00030; journal version listed in the project literature matrix
- 原文入口：https://www.sciencedirect.com/science/article/pii/S0164121220300935
- 任务：validity-based refinement of formula-cell clusters and defect detection
- 推理需要真值：`false`
- 输入：formula clusters; single-cell validity; multi-cell validity; whole-cluster validity
- 输出：refined clusters; missing/inconsistent formula detections
- 原生指标：cluster validity; defect detection precision/recall where reported
- 可兼容指标：region_hit or action metrics after a fixed mapping
- 不可混用：direct source MRR without a common output contract
- 允许主张：validity-based cluster refinement is established prior work
- 禁止主张：FormulaGuard's role refinement is independently novel or a reproduced WARDER tool

## 4. AmCheck

- 方法身份：`related_work_only`
- 实现状态：`no_public_official_runner_located`
- 引用：Dou et al., ICSE 2014, DOI 10.1145/2568225.2568316
- 原文入口：https://doi.org/10.1145/2568225.2568316
- 任务：ambiguous-computation smell detection and constraint-based formula repair
- 推理需要真值：`false`
- 输入：cell arrays; formulas; current values; constraints
- 输出：ambiguous arrays; inferred formula patterns; repair proposals
- 原生指标：smell detection; repair accuracy
- 可兼容指标：repair metrics only on a shared repair-labelled subset
- 不可混用：silent-source ranking claims from repair accuracy
- 允许主张：formula-pattern inference, cell-array ambiguity and constraint repair are established
- 禁止主张：AmCheck is a directly runnable source-localization baseline in this project

## 5. SEDMR

- 方法身份：`related_work_only`
- 实现状态：`full_preprint_reviewed_no_runner_located`
- 引用：Yang et al., Information and Software Technology 194 (2026), 108074, DOI 10.1016/j.infsof.2026.108074
- 原文入口：https://doi.org/10.1016/j.infsof.2026.108074
- 任务：metamorphic spreadsheet error-cell detection
- 推理需要真值：`false`
- 输入：formula-cell arrays; input/value perturbations; formula-pattern perturbations; selected metamorphic relations
- 输出：relation violations; detected/error-marked cells
- 原生指标：precision; recall; F1
- 可兼容指标：precision/recall/F1 on a separately defined detection task
- 不可混用：using detection F1 as source-localization MRR
- 允许主张：oracle-free perturbation and metamorphic spreadsheet detection predate this project
- 禁止主张：FormulaGuard is the first spreadsheet metamorphic detector or reproduces the published SEDMR evaluation

## 6. Spreadsheet SFL/SENDYS/ConBug family

- 方法身份：`related_work_only`
- 实现状态：`paper_reviewed_no_runner_located`
- 引用：Hofer et al., FASE 2013, DOI 10.1007/978-3-642-37057-1_6
- 原文入口：https://doi.org/10.1007/978-3-642-37057-1_6
- 任务：truth-assisted spreadsheet fault localization and debugging
- 推理需要真值：`true`
- 输入：test inputs; expected output values; pass/fail evidence; dependency traces
- 输出：suspicious-cell rankings; diagnoses; dynamic slices
- 原生指标：fault-localization ranking and diagnosis metrics
- 可兼容指标：oracle-assisted reference only
- 不可混用：unlabeled comparison to FormulaGuard's no-output contract
- 允许主张：dependency-cone fault localization is an oracle-assisted reference line
- 禁止主张：FormulaGuard invented spreadsheet fault localization or can be compared as an equal-input method

## 7. LaMirage

- 方法身份：`related_work_only`
- 实现状态：`paper_reference_only`
- 引用：Bavishi et al., 2022
- 原文入口：https://www.microsoft.com/en-us/research/publication/lamirage-neurosymbolic-repair-for-low-code-formula-languages/
- 任务：neurosymbolic formula repair
- 推理需要真值：`false`
- 输入：formula context; repair constraints; training/repair examples as specified by the method
- 输出：formula repair candidates
- 原生指标：repair exact match/validity
- 可兼容指标：repair-only supplement on a shared labelled subset
- 不可混用：silent source localization superiority
- 允许主张：neurosymbolic formula repair is established related work
- 禁止主张：candidate repair generation is a new FormulaGuard contribution

## 8. FLAME

- 方法身份：`related_work_only`
- 实现状态：`paper_reference_only`
- 引用：FLAME: A Small Language Model for Spreadsheet Formulas, 2023
- 原文入口：https://arxiv.org/abs/2301.13779
- 任务：learned spreadsheet-formula generation/repair
- 推理需要真值：`false`
- 输入：formula language context; training corpus
- 输出：generated formula candidates
- 原生指标：formula generation accuracy
- 可兼容指标：repair-only supplement if a shared labelled task is fixed
- 不可混用：no-truth source ranking comparison
- 允许主张：learned formula generation is established related work
- 禁止主张：a generated candidate is evidence that the source cell is erroneous

## 9. Selective prediction / reject option

- 方法身份：`related_work_only`
- 实现状态：`theory_reference_only`
- 引用：Geifman and El-Yaniv, 2017, arXiv:1705.08500
- 原文入口：https://arxiv.org/abs/1705.08500
- 任务：selective classification with rejection and human handling of uncertain cases
- 推理需要真值：`false`
- 输入：prediction score; selection/rejection rule; labels for evaluation
- 输出：selected actions; rejected cases; risk-coverage curve
- 原生指标：coverage; selective risk; risk-coverage
- 可兼容指标：acted precision, action coverage and review cost
- 不可混用：selective prediction as a novel FormulaGuard algorithm
- 允许主张：rejection and risk-coverage provide the evaluation framework for an optional review action
- 禁止主张：abstention, coverage or expert handoff is newly invented here

## Gate 1 结论

方法卡完整，官方当前 ExceLint-core 的 Linux headless CLI 已构建并在样例和
两个项目工作簿上重复运行一致。其他方法没有已确认可直接运行的原始 runner，
因此只能作为相关工作或后续明确标注的复现/代理；不得声称已超过这些原工具。
下一步是 Gate 2 的无标签失败图谱和原子信号审计。
