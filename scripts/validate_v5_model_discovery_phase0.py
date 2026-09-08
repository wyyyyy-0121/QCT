"""Validate the model-discovery Phase 0 contract and reproduce its design audit.

This script deliberately does not run a model or read either 240+120 package.  It
checks the tracked Phase 0 ledger and computes an exact, assumption-labelled
paired sign-test sensitivity table for the planned group-level comparison.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "research/V5_MODEL_DISCOVERY_DATA_LEDGER.json"
STATUS_PATH = ROOT / "research/V5_MODEL_DISCOVERY_CURRENT_STATUS.md"
CONTRACT_PATH = ROOT / "research/V5_MODEL_DISCOVERY_TASK_CONTRACT.md"
DECISION_LOG_PATH = ROOT / "research/V5_MODEL_DISCOVERY_DECISION_LOG.md"
GATE_RESULT_PATH = ROOT / "research/V5_MODEL_DISCOVERY_PHASE0_GATE_RESULT.md"
PLAN_PATH = ROOT / "research/V5_CORE_FIRST_PRINCIPLES_DISCOVERY_PLAN.md"
POWER_JSON_PATH = ROOT / "research/V5_MODEL_DISCOVERY_POWER_REPORT.json"
POWER_MD_PATH = ROOT / "research/V5_MODEL_DISCOVERY_POWER_REPORT.md"
PHASE0_AUDIT_PATH = ROOT / "results/core_reset_b_phase0/data_audit.json"

REQUIRED_COHORTS = {
    "enron",
    "info1",
    "public_pressure",
    "historical_100",
    "existing_synthetic",
    "old_trial_240_120",
    "new_custodian_240_120",
    "forepbench",
    "spreadsheetbench",
}
FORBIDDEN_TERMS_IN_MODEL_DISCOVERY = (
    "V5-PSL-dev1",
    "V5-PSL-dev1-rev1",
    "core-reset-c",
)


def _binom_pmf(n: int, k: int, probability: float) -> float:
    if k < 0 or k > n:
        return 0.0
    if probability == 0.0:
        return 1.0 if k == 0 else 0.0
    if probability == 1.0:
        return 1.0 if k == n else 0.0
    return math.comb(n, k) * probability**k * (1.0 - probability) ** (n - k)


def _binom_cdf(n: int, k: int, probability: float) -> float:
    return sum(_binom_pmf(n, j, probability) for j in range(k + 1))


def _binom_sf(n: int, k: int, probability: float) -> float:
    return sum(_binom_pmf(n, j, probability) for j in range(k, n + 1))


def exact_paired_sign_power(
    n: int,
    delta: float,
    discordance_rate: float,
    *,
    alpha: float = 0.05,
) -> float:
    """Return exact two-sided sign-test power for paired binary outcomes.

    ``delta`` is the candidate-minus-baseline success-rate difference.  The
    marginal paired model has b=(d+delta)/2 candidate-only wins and
    c=(d-delta)/2 baseline-only wins, where d is the discordance rate.  This
    is a sensitivity calculation, not a claim about the unknown data process.
    """

    if n <= 0:
        raise ValueError("n must be positive")
    if not 0.0 <= discordance_rate <= 1.0:
        raise ValueError("discordance_rate must be in [0, 1]")
    if abs(delta) > discordance_rate + 1e-12:
        raise ValueError("absolute delta cannot exceed discordance rate")
    if discordance_rate == 0.0:
        return 0.0

    candidate_only = (discordance_rate + delta) / 2.0
    conditional_win_rate = candidate_only / discordance_rate
    power = 0.0
    for discordant in range(n + 1):
        probability_discordant = _binom_pmf(n, discordant, discordance_rate)
        for wins in range(discordant + 1):
            lower = _binom_cdf(discordant, wins, 0.5)
            upper = _binom_sf(discordant, wins, 0.5)
            p_value = min(1.0, 2.0 * min(lower, upper))
            if p_value < alpha:
                power += probability_discordant * _binom_pmf(
                    discordant, wins, conditional_win_rate
                )
    return power


def build_power_report() -> dict[str, Any]:
    sample_sizes = [25, 30]
    deltas = [0.05, 0.10, 0.20, 0.30]
    discordance_rates = [0.20, 0.40, 0.60, 0.80]
    rows: list[dict[str, Any]] = []
    for n in sample_sizes:
        for delta in deltas:
            for discordance in discordance_rates:
                if delta > discordance:
                    continue
                rows.append({
                    "n_structure_groups": n,
                    "delta": delta,
                    "discordance_rate": discordance,
                    "exact_two_sided_sign_power": round(
                        exact_paired_sign_power(n, delta, discordance), 12
                    ),
                })

    five_pp = [
        row for row in rows if math.isclose(row["delta"], 0.05)
    ]
    summary = {}
    for n in sample_sizes:
        values = [
            row["exact_two_sided_sign_power"]
            for row in five_pp
            if row["n_structure_groups"] == n
        ]
        summary[str(n)] = {
            "five_pp_min_power": min(values),
            "five_pp_max_power": max(values),
            "five_pp_mean_power": round(sum(values) / len(values), 12),
        }

    return {
        "protocol": "formulaguard_model_discovery_phase0_power_v1",
        "date": "2026-08-31",
        "status": "design_sensitivity_not_observed_effect",
        "test": {
            "name": "exact_conditional_two_sided_paired_sign_test",
            "alpha": 0.05,
            "unit": "structure_group",
            "null": "candidate and V4 have equal paired success probability",
            "alternative": "candidate success exceeds V4 by delta",
            "discordance_rates": discordance_rates,
        },
        "planned_sample_sizes": sample_sizes,
        "effect_grid": deltas,
        "rows": rows,
        "summary_for_five_percentage_points": summary,
        "decision": {
            "five_pp_is_not_well_powered_at_25_or_30_groups": all(
                summary[str(n)]["five_pp_max_power"] < 0.80 for n in sample_sizes
            ),
            "required_action": (
                "Do not claim confirmatory 5-point superiority from 25 or 30 groups; "
                "increase independent template groups before locking, or label the "
                "result as estimation/exploratory evidence."
            ),
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    return value


def validate_ledger(ledger: dict[str, Any], phase0_audit: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if ledger.get("protocol") != "formulaguard_model_discovery_data_ledger_v1":
        errors.append("unexpected ledger protocol")
    cohorts = ledger.get("cohorts")
    if not isinstance(cohorts, list):
        return ["ledger cohorts must be a list"]
    cohort_ids = {item.get("id") for item in cohorts if isinstance(item, dict)}
    missing = REQUIRED_COHORTS - cohort_ids
    if missing:
        errors.append(f"missing cohorts: {sorted(missing)}")
    contract = ledger.get("prediction_contract", {})
    if contract.get("labels_allowed_during_prediction") is not False:
        errors.append("prediction contract allows labels")
    if contract.get("review_budget") != 5:
        errors.append("review budget is not five")
    for item in cohorts:
        if not isinstance(item, dict):
            errors.append("cohort entry is not an object")
            continue
        if item.get("id") in {"old_trial_240_120", "new_custodian_240_120"}:
            if item.get("label_status") != "unread":
                errors.append(f"{item.get('id')} is not marked unread")
            if item.get("path") != "outside_repository_owner_supplied":
                errors.append(f"{item.get('id')} has an in-repository path")
    source_audit = ledger.get("source_audit", {})
    if source_audit.get("gate_0_passed") is not True:
        errors.append("source Phase 0 audit is not marked passed")
    expected_counts = {
        "events": 220,
        "provenance_units": phase0_audit.get("facts", {}).get(
            "all_provenance_units", 147
        ),
        "structure_groups": phase0_audit.get("facts", {}).get(
            "all_structure_clusters", 137
        ),
    }
    for key, expected in expected_counts.items():
        if source_audit.get(key) != expected:
            errors.append(
                f"ledger {key} count {source_audit.get(key)!r} != Phase 0 {expected!r}"
            )
    if phase0_audit.get("gate_0_passed") is not True:
        errors.append("tracked Phase 0 audit is not passed")
    return errors


def validate_documents() -> list[str]:
    errors: list[str] = []
    for path in (STATUS_PATH, CONTRACT_PATH, DECISION_LOG_PATH, GATE_RESULT_PATH, PLAN_PATH):
        if not path.is_file():
            errors.append(f"missing document: {path.relative_to(ROOT)}")
    for path in (STATUS_PATH, CONTRACT_PATH, DECISION_LOG_PATH, GATE_RESULT_PATH):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for term in FORBIDDEN_TERMS_IN_MODEL_DISCOVERY:
                if term in text:
                    errors.append(
                        f"historical/unauthorized term {term!r} appears in {path.name}"
                    )
    return errors


def validate_power_report(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = build_power_report()
    if report != expected:
        errors.append("power report does not match deterministic calculation")
    if not report.get("decision", {}).get(
        "five_pp_is_not_well_powered_at_25_or_30_groups"
    ):
        errors.append("power decision unexpectedly allows a 5-point claim")
    return errors


def markdown_power_report(report: dict[str, Any]) -> str:
    summary = report["summary_for_five_percentage_points"]
    lines = [
        "# FormulaGuard model-discovery Phase 0 功效与可检测差异审计",
        "",
        "日期：2026-08-31",
        "状态：设计敏感性分析，不是观察到的模型效果",
        "",
        "## 结论",
        "",
        "在一个结构组作为一个配对观测、显著性水平 `alpha=0.05`、精确双侧配对符号检验的",
        "保守计算下，25 个 Enron 工作簿组或 30 个最终模板组都不足以可靠检出 5 个百分",
        "点的 Top-5 改善。这里的功效取决于未知的配对不一致率；即使在本表设定的最好",
        "不一致率条件下，25 组最大功效约为 `{:.2f}%`，30 组最大功效约为 `{:.2f}%`。".format(
            100 * summary["25"]["five_pp_max_power"],
            100 * summary["30"]["five_pp_max_power"],
        ),
        "",
        "因此，正式盲测前必须增加独立模板组，或把结果明确限定为估计/探索性证据；",
        "不得在评分后降低 5 个百分点门槛，也不得把事件数量当作独立结构组数量。",
        "",
        "## 计算定义",
        "",
        "- 单位：工作簿/模板 `structure_group`，不是事件行。",
        "- 二元结果：每组 Top-5 是否命中；候选模型与 V4 成对比较。",
        "- `delta`：候选命中率减 V4 命中率。",
        "- `discordance_rate`：两方法在一组上结果不同的概率，分别审计 `0.20/0.40/0.60/0.80`。",
        "- 条件于不一致组数，对候选胜负使用精确二项分布；双侧 `p < 0.05` 记为检出。",
        "- 这是设计敏感性，不是对未来数据生成过程的断言。",
        "",
        "## 5 个百分点网格",
        "",
        "| 结构组数 | 最小功效 | 最大功效 | 平均功效 |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for n in (25, 30):
        item = summary[str(n)]
        lines.append(
            f"| {n} | {100 * item['five_pp_min_power']:.2f}% | "
            f"{100 * item['five_pp_max_power']:.2f}% | "
            f"{100 * item['five_pp_mean_power']:.2f}% |"
        )
    lines.extend([
        "",
        "完整参数网格和可复算 JSON 位于 `V5_MODEL_DISCOVERY_POWER_REPORT.json`；",
        "生成/校验命令为：",
        "",
        "```bash",
        "python scripts/validate_v5_model_discovery_phase0.py --write",
        "python scripts/validate_v5_model_discovery_phase0.py --check",
        "```",
        "",
        "## 决策边界",
        "",
        "1. Enron 的 25 组继续用于自然错误失败发现和迁移安全，不升级为确认性主结果。",
        "2. 最终盲测若仍只有 30 个模板，主张必须写成未见模板上的估计或探索性比较。",
        "3. 若要声称 5 个百分点的确认性优势，先增加独立模板组并在候选锁前登记。",
        "4. 本报告不读取旧或新 `240+120`，也不授权任何新模型实现。",
        "",
    ])
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write deterministic power artifacts")
    parser.add_argument("--check", action="store_true", help="validate Phase 0 artifacts")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.write and not args.check:
        parser.error("choose --write or --check")

    report = build_power_report()
    if args.write:
        POWER_JSON_PATH.write_text(
            json.dumps(report, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        POWER_MD_PATH.write_text(markdown_power_report(report), encoding="utf-8")

    if args.check:
        errors: list[str] = []
        if not LEDGER_PATH.is_file():
            errors.append(f"missing ledger: {LEDGER_PATH.relative_to(ROOT)}")
        else:
            errors.extend(validate_ledger(_read_json(LEDGER_PATH), _read_json(PHASE0_AUDIT_PATH)))
        errors.extend(validate_documents())
        if not POWER_JSON_PATH.is_file() or not POWER_MD_PATH.is_file():
            errors.append("power artifacts are missing; run --write first")
        else:
            errors.extend(validate_power_report(_read_json(POWER_JSON_PATH)))
            if POWER_MD_PATH.read_text(encoding="utf-8") != markdown_power_report(report):
                errors.append("power Markdown does not match deterministic calculation")
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print("phase0 validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
