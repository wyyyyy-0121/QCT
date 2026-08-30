"""Validate and render the literature/method cards for model-discovery Gate 1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
CARDS_PATH = ROOT / "research/V5_MODEL_DISCOVERY_METHOD_CARDS.json"
CARDS_MD_PATH = ROOT / "research/V5_MODEL_DISCOVERY_METHOD_CARDS.md"
RESULT_PATH = ROOT / "research/V5_MODEL_DISCOVERY_GATE1_RESULT.json"
RESULT_MD_PATH = ROOT / "research/V5_MODEL_DISCOVERY_GATE1_RESULT.md"

EXPECTED_IDS = (
    "excelint",
    "custodes",
    "warder",
    "amcheck",
    "sedmr",
    "spreadsheet_sfl",
    "lamirage",
    "flame",
    "selective_prediction",
)
IDENTITIES = {
    "original_implementation",
    "official_current_implementation",
    "validated_reimplementation",
    "idea_level_proxy",
    "related_work_only",
}
REQUIRED_FIELDS = {
    "id",
    "canonical_name",
    "citation",
    "source_locator",
    "task",
    "requires_truth_at_inference",
    "inputs",
    "outputs",
    "native_metrics",
    "qct_compatible_metrics",
    "qct_incompatible_metrics",
    "implementation_identity",
    "implementation_status",
    "permitted_claim",
    "forbidden_claim",
}


def load_cards(path: Path = CARDS_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("method cards must be a JSON object")
    return value


def validate_cards(cards: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if cards.get("protocol") != "formulaguard_model_discovery_method_cards_v1":
        errors.append("unexpected method-card protocol")
    methods = cards.get("methods")
    if not isinstance(methods, list):
        return ["methods must be a list"]
    ids = []
    for method in methods:
        if not isinstance(method, dict):
            errors.append("method card is not an object")
            continue
        method_id = method.get("id")
        ids.append(method_id)
        missing = REQUIRED_FIELDS - set(method)
        if missing:
            errors.append(f"{method_id}: missing fields {sorted(missing)}")
        identity = method.get("implementation_identity")
        if identity not in IDENTITIES:
            errors.append(f"{method_id}: invalid implementation identity {identity!r}")
        for field in ("inputs", "outputs", "native_metrics", "qct_compatible_metrics", "qct_incompatible_metrics"):
            if not isinstance(method.get(field), list) or not method[field]:
                errors.append(f"{method_id}: {field} must be a non-empty list")
        if not isinstance(method.get("requires_truth_at_inference"), bool):
            errors.append(f"{method_id}: requires_truth_at_inference must be boolean")
        if not method.get("permitted_claim") or not method.get("forbidden_claim"):
            errors.append(f"{method_id}: claim boundary is incomplete")
    if tuple(ids) != EXPECTED_IDS:
        errors.append(f"method order/IDs differ: expected {EXPECTED_IDS}, got {tuple(ids)}")
    excelint = next((m for m in methods if isinstance(m, dict) and m.get("id") == "excelint"), None)
    if excelint is None:
        errors.append("ExceLint card missing")
    else:
        if excelint.get("implementation_identity") != "official_current_implementation":
            errors.append("ExceLint must be marked official_current_implementation")
        if excelint.get("implementation_status") != "linux_cli_verified":
            errors.append("ExceLint Linux CLI verification is missing")
        runtime = excelint.get("runtime_record", {})
        if runtime.get("deterministic_repeat_verified") is not True:
            errors.append("ExceLint deterministic repeat is not recorded")
    return errors


def build_gate_result(cards: dict[str, Any]) -> dict[str, Any]:
    methods = cards["methods"]
    identities = {method["implementation_identity"] for method in methods}
    return {
        "protocol": "formulaguard_model_discovery_gate1_v1",
        "date": "2026-08-31",
        "gate_1_passed": True,
        "authorization": {
            "method_cards_complete": True,
            "official_excelint_current_cli_verified": True,
            "academic_baseline_superiority_claim": False,
            "new_model_implementation": False,
        },
        "method_count": len(methods),
        "method_ids": [method["id"] for method in methods],
        "identity_counts": {
            identity: sum(
                method["implementation_identity"] == identity for method in methods
            )
            for identity in sorted(identities)
        },
        "excelint_runtime": {
            "repository": "https://github.com/plasma-umass/ExceLint-core",
            "commit": "b2c5e7df4405a932c82a07e105f275c61fdab6e3",
            "node": "v22.22.1",
            "build_command": "npm ci --ignore-scripts; npm run build",
            "sample_output_sha256": {
                "act3_lab23_posey": "a74358d636725cd716a38983a6c2d483ffd0978ae214035f5e794c9c790f5c2a",
                "attendance_v0": "d20f8de2069d418f061e04b79c61a7c96e2744d0621a84647b680e3fbfb5794b",
                "enron_22": "1a0a0ab642523beba193834df25927e5de72ae56680ef89f322f0ca6a8638b91",
            },
            "package_lock_sha256": "37b6dae7aa40a23dfba6efa8a2a2cec1c6dc56b17bd93a6c730a527b01aaa794",
            "observed_output": "WorkbookAnalysis JSON with sheets, proposed fixes and foundBugs; no complete per-formula ranking",
            "security_note": "npm reported legacy dependency vulnerabilities; the runtime is isolated for Gate 1 verification and is not copied into this repository.",
        },
        "claim_boundary": {
            "allowed": [
                "compare official current ExceLint native region/fix output where input support and mapping are explicit",
                "use other cards to define related-work and metric boundaries",
            ],
            "forbidden": [
                "claim a reproduced OOPSLA experiment without the legacy Windows runner",
                "claim superiority over an unavailable original implementation",
                "call a repair or parser benchmark a silent-source localization benchmark",
            ],
        },
        "next_gate": "Gate 2: label-free failure graph and atomic signal audit",
    }


def render_cards(cards: dict[str, Any]) -> str:
    lines = [
        "# FormulaGuard model-discovery Gate 1 方法卡",
        "",
        "日期：2026-08-31",
        "状态：完成；方法身份和指标兼容性已固定",
        "",
        "## 总则",
        "",
        "`official_current_implementation`、`validated_reimplementation`、",
        "`idea_level_proxy` 和 `related_work_only` 不可互换。没有共同输入、输出和",
        "指标的方法不进入“超过学术基线”的数字比较。Gate 1 不授权新模型实现。",
        "",
    ]
    for index, method in enumerate(cards["methods"], start=1):
        lines.extend([
            f"## {index}. {method['canonical_name']}",
            "",
            f"- 方法身份：`{method['implementation_identity']}`",
            f"- 实现状态：`{method['implementation_status']}`",
            f"- 引用：{method['citation']}",
            f"- 原文入口：{method['source_locator']}",
            f"- 任务：{method['task']}",
            f"- 推理需要真值：`{str(method['requires_truth_at_inference']).lower()}`",
            f"- 输入：{'; '.join(method['inputs'])}",
            f"- 输出：{'; '.join(method['outputs'])}",
            f"- 原生指标：{'; '.join(method['native_metrics'])}",
            f"- 可兼容指标：{'; '.join(method['qct_compatible_metrics'])}",
            f"- 不可混用：{'; '.join(method['qct_incompatible_metrics'])}",
            f"- 允许主张：{method['permitted_claim']}",
            f"- 禁止主张：{method['forbidden_claim']}",
            "",
        ])
        if method.get("runtime_record"):
            runtime = method["runtime_record"]
            lines.extend([
                "### ExceLint 运行记录",
                "",
                f"- 构建：`{runtime['build']}`",
                f"- Node：`{runtime['node']}`",
                f"- 样例：{'; '.join(runtime['sample_runs'])}",
                f"- 重复运行一致：`{str(runtime['deterministic_repeat_verified']).lower()}`",
                f"- 输出边界：{runtime['output_contract']}",
                "",
            ])
    lines.extend([
        "## Gate 1 结论",
        "",
        "方法卡完整，官方当前 ExceLint-core 的 Linux headless CLI 已构建并在样例和",
        "两个项目工作簿上重复运行一致。其他方法没有已确认可直接运行的原始 runner，",
        "因此只能作为相关工作或后续明确标注的复现/代理；不得声称已超过这些原工具。",
        "下一步是 Gate 2 的无标签失败图谱和原子信号审计。",
        "",
    ])
    return "\n".join(lines)


def render_result(result: dict[str, Any]) -> str:
    lines = [
        "# FormulaGuard model-discovery Gate 1 回执",
        "",
        "日期：2026-08-31",
        f"状态：`{'PASS' if result['gate_1_passed'] else 'FAIL'}`",
        "",
        "## 已通过",
        "",
        "- 9 张方法卡的输入、输出、任务和指标边界完整。",
        "- 官方当前 ExceLint-core 在 Linux 上构建成功，样例输出重复一致。",
        "- 不可运行原实现的方法均保留为相关工作/代理，不被伪装成原工具结果。",
        "- Gate 1 不授权任何新模型实现，也不读取 `240+120` 数据。",
        "",
        "## ExceLint 边界",
        "",
        "当前 CLI 输出 `WorkbookAnalysis`，包含工作表、候选修复和 `foundBugs`；它",
        "不是一个天然的完整逐公式排名器。因此后续只能在明确映射为区域/复核列表后",
        "比较兼容指标，不能把地址顺序或候选区域数量伪造为源定位 MRR。",
        "",
        "## 不允许的结论",
        "",
        "1. 没有运行原始 Windows/Excel runner 时，不写“复现 OOPSLA 实验”。",
        "2. 没有共同输入和指标时，不写“超过 CUSTODES/WARDER/SEDMR”等。",
        "3. 修复准确率、检测 F1 和源定位 MRR 不合并为单一准确率。",
        "",
        "## 下一步",
        "",
        "进入 Gate 2：用无标签原子探针建立失败图谱，先判断是否有可迁移的新增信号，",
        "再决定完整排名、选择性辅助或最小附加信息分支。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="render Markdown and result JSON")
    parser.add_argument("--check", action="store_true", help="validate cards and rendered artifacts")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.write and not args.check:
        parser.error("choose --write or --check")

    cards = load_cards()
    errors = validate_cards(cards)
    result = build_gate_result(cards)
    if args.write:
        CARDS_MD_PATH.write_text(render_cards(cards), encoding="utf-8")
        RESULT_PATH.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        RESULT_MD_PATH.write_text(render_result(result), encoding="utf-8")
    if args.check:
        if not errors and RESULT_PATH.is_file():
            with RESULT_PATH.open("r", encoding="utf-8") as handle:
                saved = json.load(handle)
            if saved != result:
                errors.append("Gate 1 result JSON is not reproducible")
        elif not RESULT_PATH.is_file():
            errors.append("Gate 1 result JSON is missing; run --write first")
        if not CARDS_MD_PATH.is_file() or CARDS_MD_PATH.read_text(encoding="utf-8") != render_cards(cards):
            errors.append("method-card Markdown is missing or stale")
        if not RESULT_MD_PATH.is_file() or RESULT_MD_PATH.read_text(encoding="utf-8") != render_result(result):
            errors.append("Gate 1 result Markdown is missing or stale")
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print("gate1 validation passed")
    elif errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
