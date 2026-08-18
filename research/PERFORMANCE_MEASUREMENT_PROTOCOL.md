# FormulaGuard 性能测量协议（v3）

## 1. 目的

性能实验回答两个不同的问题，必须分别测量、分别报告：

1. **单工作簿延迟（latency）**：给定一个工作簿后，FormulaGuard 完成解析和定位要多久？
2. **批量吞吐（throughput）**：在多份互不依赖的工作簿上，一台机器每秒能完成多少诊断任务？

二者不能混为同一指标。尤其是批量运行时，各进程会争夺 CPU 缓存、内存带宽和磁盘读取资源；其中单个任务的耗时不能作为“单工作簿延迟”写入论文。

## 2. 算法与硬件边界

当前实现采用 Python 公式解析、依赖图遍历、候选修复及反事实求值。这些步骤不调用 PyTorch、CUDA 或其他 GPU 计算库，因此 GPU 利用率接近零是预期行为，而非故障。

每一个独立工作簿诊断任务主要受 Python CPU 计算限制。批量任务之间不存在数据依赖，因而可安全使用多进程并行；同一工作簿的定位任务仍按确定性顺序完成，避免为追求利用率而改变算法结果或污染单表延迟测量。

## 3. 预登记命令

在 `cmd` 中运行。结果文件名必须包含模式，避免误用。

### 3.1 论文主指标：单工作簿延迟

```bat
cd /d D:\code\QCT
python scripts\run_performance.py --input data\scaling --output results\v3_full\performance_v3_latency.csv --methods formulaguard_v3 --candidate-limit 15 --repeats 5 --mode latency --workers 1
```

报告每个公式规模的解析时间中位数、定位时间中位数和 P95。该命令故意只使用一个进程；其结果才可解释为一次孤立诊断的延迟。

### 3.2 补充指标：多核批量吞吐

```bat
cd /d D:\code\QCT
python scripts\run_performance.py --input data\scaling --output results\v3_full\performance_v3_throughput.csv --methods formulaguard_v3 --candidate-limit 15 --repeats 5 --mode throughput --workers 16
```

脚本会把较大的工作簿优先提交给进程池，以减少结尾只剩大任务时的空闲尾部。对于 Ryzen 9 9955HX3D，16 个 worker 对应其 16 个物理核心，是默认的稳健上限；不预设 28 或 32 个 worker，以免超线程争抢缓存造成表面满载、实际吞吐下降。

吞吐输出中的 `*_metadata.json` 记录总墙钟时间、任务数和 `jobs_per_second`。论文只能把它表述为“批量诊断吞吐”，不得把其中的 `localization_seconds` 称为孤立延迟。

## 4. 运行顺序与停止规则

1. 先运行 3.1，保证论文核心效率结论可复现。
2. 再运行 3.2，作为硬件利用和部署能力的补充。
3. 两个命令不可同时运行；否则延迟数据受争抢污染。
4. 任一运行异常中止时，删除该轮未完成的同名 CSV、summary CSV 和 metadata JSON 后重跑；不混合不同轮次的结果。

## 5. 结果解释限制

- 规模工作簿是合成的，只可说明随公式数量增长的运行行为，不能证明真实表格的准确率。
- 该性能实验不训练模型，也不调整任何冻结的定位权重或阈值。
- 若使用不同机器、不同 Python 版本或不同 worker 数，必须作为单独一轮结果报告，不能与正式结果合并取平均。
