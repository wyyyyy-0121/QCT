# 来源与归属

- `src/structuralguard/`：来自用户提供的 `StructuralGuard_handoff_20260903_complete.zip`。
- `src/formulaguard/` 的基础解析、工作簿和公式求值模块：选择性参考并保留自 [wyyyyy-0121/QCT 的 codex/linux-migration 分支](https://github.com/wyyyyy-0121/QCT/tree/codex/linux-migration)。上游采用 MIT License，许可证全文见 `vendor/FORMULAGUARD_LICENSE.txt`。
- `src/hybridguard/`、测试工作簿生成器、评估协议与 HybridGuard 融合逻辑：为本次实验新增。

HybridGuard 不是上游 FormulaGuard 的官方模型或官方版本。仓库中的V4文件仅为历史复现实验保留；当前默认运行入口已不再调用V4。

## V5替换

`src/formulaguard/v5_structural_guard.py` 来自用户提供的 `QCT_StructuralGuard_V5_vs_V4_20260903.zip`。源包记录的文件SHA-256为 `26ee27bfc93366fc0001dda680fd8e55a51a42e935d5fba955d89e3e754e347b`；项目副本与源文件文本相同，仅换行格式可能不同。V5声明其排名器独立于V4，本项目从0.3.0起用它替代V4运行入口。
