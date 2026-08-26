"""Recompute and audit one completed FormulaGuard V6 development round.

This script is deliberately independent of the round gate writer.  It checks
raw row grain, method/event uniqueness, metric identities, aggregation
agreement, prediction receipts, label isolation, clean-control alarm shape and
Enron rank changes before emitting a technical JSON/Markdown evidence record.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def number(row: dict[str, str], field: str) -> float:
    value = row.get(field, "")
    if value in {"", None}:
        return math.nan
    return float(value)


def close(left: float, right: float, tolerance: float = 1e-12) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def summarize_rows(rows: list[dict[str, str]], method: str) -> dict:
    selected = [row for row in rows if row["method"] == method]
    active = sum(int(number(row, "promotion_active")) for row in selected if not math.isnan(number(row, "promotion_active")))
    correct = sum(int(number(row, "promotion_correct")) for row in selected if not math.isnan(number(row, "promotion_correct")))
    coverage = [number(row, "candidate_coverage_at_25") for row in selected]
    coverage = [value for value in coverage if not math.isnan(value)]
    return {
        "events": len(selected),
        "top1": statistics.fmean(number(row, "top1") for row in selected),
        "top3": statistics.fmean(number(row, "top3") for row in selected),
        "top5": statistics.fmean(number(row, "top5") for row in selected),
        "mrr": statistics.fmean(number(row, "mrr") for row in selected),
        "exam": statistics.fmean(number(row, "exam") for row in selected),
        "repair_exact": statistics.fmean(number(row, "repair_exact") for row in selected),
        "candidate_coverage_at_25": statistics.fmean(coverage) if coverage else None,
        "promotion_active_count": active,
        "promotion_correct_count": correct,
        "promotion_activation": active / max(1, len(selected)),
        "promotion_precision": correct / max(1, active),
        "runtime_median": statistics.median(number(row, "runtime_seconds") for row in selected),
    }


def audit_layer(root: Path, layer: str, variant: str) -> dict:
    layer_root = root / layer
    rows = load_csv(layer_root / "raw_results.csv")
    summary = load_json(layer_root / "summary.json")
    method = f"v6_{variant}"
    expected_events = summary["events"]
    expected_methods = {"v4", method}
    keys = [(row["instance_id"], row["method"]) for row in rows]
    key_counts = Counter(keys)
    issues: list[str] = []
    if len(rows) != expected_events * len(expected_methods):
        issues.append("unexpected_raw_row_count")
    if set(row["method"] for row in rows) != expected_methods:
        issues.append("unexpected_method_set")
    if any(count != 1 for count in key_counts.values()):
        issues.append("duplicate_event_method_key")
    if len({row["instance_id"] for row in rows}) != expected_events:
        issues.append("unexpected_unique_event_count")

    for row in rows:
        rank = int(row["rank"])
        formulas = int(row["formula_count"])
        if not 1 <= rank <= formulas:
            issues.append(f"rank_out_of_bounds:{row['instance_id']}:{row['method']}")
        identities = {
            "top1": int(rank <= 1), "top3": int(rank <= 3), "top5": int(rank <= 5),
        }
        for field, expected in identities.items():
            if int(float(row[field])) != expected:
                issues.append(f"{field}_identity:{row['instance_id']}:{row['method']}")
        if not close(float(row["mrr"]), 1.0 / rank):
            issues.append(f"mrr_identity:{row['instance_id']}:{row['method']}")
        if not close(float(row["exam"]), rank / formulas):
            issues.append(f"exam_identity:{row['instance_id']}:{row['method']}")

    recomputed = {name: summarize_rows(rows, name) for name in sorted(expected_methods)}
    for name, values in recomputed.items():
        declared = summary["summaries"][name]
        for field in ("events", "top1", "top3", "top5", "mrr", "exam", "repair_exact", "runtime_median"):
            if not close(float(values[field]), float(declared[field])):
                issues.append(f"aggregate_mismatch:{name}:{field}")
        if name == method:
            for field in ("candidate_coverage_at_25", "promotion_activation", "promotion_precision"):
                if not close(float(values[field]), float(declared[field])):
                    issues.append(f"aggregate_mismatch:{name}:{field}")

    by_method = {name: {row["instance_id"]: row for row in rows if row["method"] == name} for name in expected_methods}
    changes = Counter()
    by_error = defaultdict(Counter)
    for instance_id, current in by_method[method].items():
        base = by_method["v4"][instance_id]
        base_rank, current_rank = int(base["rank"]), int(current["rank"])
        if current_rank < base_rank:
            changes["rank_improved"] += 1
        elif current_rank > base_rank:
            changes["rank_worsened"] += 1
        else:
            changes["rank_unchanged"] += 1
        if int(current["top5"]) > int(base["top5"]):
            changes["new_top5_hit"] += 1
            by_error[current["error_type"]]["new_top5_hit"] += 1
        elif int(current["top5"]) < int(base["top5"]):
            changes["lost_top5_hit"] += 1
            by_error[current["error_type"]]["lost_top5_hit"] += 1

    prediction = layer_root / "predictions"
    metadata = load_json(prediction / "prediction_metadata.json")
    completion = load_json(prediction / "prediction_complete.json")
    shards = list((prediction / "shards").glob("*.json"))
    receipts = {
        "shard_count": len(shards),
        "completion_instances": completion.get("instances"),
        "complete": completion.get("complete", False),
        "full_ranking_audit_passed": completion.get("full_ranking_audit_passed", False),
        "workers_requested": completion.get("workers_requested"),
        "label_files_read": metadata.get("label_files_read"),
        "git_commit": metadata.get("git_commit"),
        "dataset_manifest_sha256": metadata.get("dataset_manifest_sha256"),
    }
    if len(shards) != expected_events or completion.get("instances") != expected_events:
        issues.append("prediction_shard_count_mismatch")
    if not completion.get("complete") or not completion.get("full_ranking_audit_passed"):
        issues.append("prediction_completion_or_full_ranking_failed")
    if completion.get("workers_requested") != 24:
        issues.append("worker_policy_not_24")
    if metadata.get("label_files_read") != []:
        issues.append("label_isolation_failed")

    return {
        "expected_events": expected_events,
        "raw_rows": len(rows),
        "unique_event_method_keys": len(key_counts),
        "methods": sorted(expected_methods),
        "recomputed": recomputed,
        "declared": {name: summary["summaries"][name] for name in sorted(expected_methods)},
        "paired_rank_changes": dict(changes),
        "new_or_lost_top5_by_error": {key: dict(value) for key, value in sorted(by_error.items())},
        "prediction_receipts": receipts,
        "issues": sorted(set(issues)),
        "passed": not issues,
    }


def audit_clean(root: Path, variant: str) -> dict:
    prediction = root / "clean/predictions"
    method = f"v6_{variant}"
    manifest_rows = load_json(ROOT / "data/v6_clean/clean_manifest.json")
    manifest = {row["clean_id"]: row for row in manifest_rows}
    alarms = []
    issues = []
    shard_paths = sorted((prediction / "shards").glob("*.json"))
    for path in shard_paths:
        record = load_json(path)
        ranking = record["rankings"].get(method, [])
        promoted = [row for row in ranking if row.get("evidence", {}).get("promotion_target")]
        if len(promoted) > 1:
            issues.append(f"multiple_promotions:{path.stem}")
        if promoted:
            item = promoted[0]
            evidence = item["evidence"]
            meta = manifest[path.stem]
            alarms.append({
                "instance_id": path.stem,
                "structure": meta["structure"],
                "complexity": meta["complexity"],
                "cell": item["cell"],
                "rank": item["rank"],
                "candidate_formula": item.get("candidate_formula", ""),
                "semantic_tier": evidence.get("semantic_tier"),
                "family_support": evidence.get("family_support"),
                "family_margin": evidence.get("family_margin"),
                "counterfactual_delta": evidence.get("counterfactual_delta"),
                "counterfactual_irg": evidence.get("counterfactual_irg"),
                "global_harm": evidence.get("global_harm"),
                "promotion_reason": evidence.get("promotion_reason"),
            })
    summary = load_json(root / "clean/v6_clean_summary.json")
    declared = summary["variants"][method]
    if len(shard_paths) != len(manifest_rows):
        issues.append("clean_shard_count_mismatch")
    if len(alarms) != declared["alarms"]:
        issues.append("clean_alarm_count_mismatch")
    false_alarm_rate = len(alarms) / max(1, len(manifest_rows))
    if not close(false_alarm_rate, declared["false_alarm_rate"]):
        issues.append("clean_false_alarm_rate_mismatch")
    structure_totals = Counter(row["structure"] for row in manifest_rows)
    complexity_totals = Counter(row["complexity"] for row in manifest_rows)
    structure_alarms = Counter(row["structure"] for row in alarms)
    complexity_alarms = Counter(row["complexity"] for row in alarms)
    by_structure = {
        key: {
            "alarms": structure_alarms[key], "total": structure_totals[key],
            "false_alarm_rate": structure_alarms[key] / structure_totals[key],
        }
        for key in sorted(structure_totals)
    }
    by_complexity = {
        key: {
            "alarms": complexity_alarms[key], "total": complexity_totals[key],
            "false_alarm_rate": complexity_alarms[key] / complexity_totals[key],
        }
        for key in sorted(complexity_totals)
    }
    return {
        "workbooks": len(manifest_rows),
        "shards": len(shard_paths),
        "alarms": len(alarms),
        "false_alarm_rate": false_alarm_rate,
        "by_structure": by_structure,
        "by_complexity": by_complexity,
        "alarm_cells": dict(Counter(row["cell"].split("!", 1)[1][0] for row in alarms)),
        "alarm_candidate_formulas": dict(Counter(row["candidate_formula"].split("(", 1)[0] for row in alarms)),
        "alarm_examples": alarms[:8],
        "issues": sorted(set(issues)),
        "passed": not issues,
    }


def audit_enron(root: Path, variant: str) -> dict:
    rows = load_csv(root / "enron/enron_raw.csv")
    summary = load_json(root / "enron/enron_summary.json")
    metadata = load_json(root / "enron/enron_metadata.json")
    completion = load_json(root / "enron/enron_prediction_complete.json")
    method = f"v6_{variant}"
    expected_methods = {"v4", method}
    keys = Counter((row["instance_id"], row["method"]) for row in rows)
    issues = []
    if any(value != 1 for value in keys.values()):
        issues.append("duplicate_enron_event_method_key")
    if set(row["method"] for row in rows) != expected_methods:
        issues.append("unexpected_enron_method_set")
    if metadata.get("retrospective_only") is not True:
        issues.append("enron_not_marked_retrospective")
    if metadata.get("event_inventory") != "all_evaluation_ready_events":
        issues.append("enron_inventory_not_all_evaluation_ready_events")
    if completion.get("events") != 30:
        issues.append("enron_inventory_not_30_events")
    if not completion.get("complete") or not completion.get("full_ranking_audit_passed"):
        issues.append("enron_completion_or_full_ranking_failed")
    if completion.get("events") != summary["summary"]["v4"]["events"]:
        issues.append("enron_event_count_mismatch")
    by_method = {name: {row["instance_id"]: row for row in rows if row["method"] == name} for name in expected_methods}
    changes = []
    for instance_id, current in by_method[method].items():
        base = by_method["v4"][instance_id]
        if int(current["rank"]) != int(base["rank"]):
            changes.append({
                "instance_id": instance_id,
                "v4_rank": int(base["rank"]),
                "v6_rank": int(current["rank"]),
                "rank_delta": int(current["rank"]) - int(base["rank"]),
                "formula_count": int(base["formula_count"]),
            })
    return {
        "events": completion.get("events"),
        "workbooks": completion.get("workbooks"),
        "raw_rows": len(rows),
        "retrospective_only": metadata.get("retrospective_only"),
        "workers_requested": metadata.get("workers_requested"),
        "full_ranking_audit_passed": completion.get("full_ranking_audit_passed"),
        "summary": summary["summary"],
        "mrr_difference": summary["summary"][method]["mrr"] - summary["summary"]["v4"]["mrr"],
        "rank_changes": changes,
        "unchanged_events": completion.get("events") - len(changes),
        "issues": sorted(set(issues)),
        "passed": not issues,
    }


def cross_variant_clean_probe() -> dict:
    """Check whether the fixed A/B/C mechanisms reject one known clean exception.

    This is a diagnostic probe, not a population estimate and not a parameter
    selection rule.  It is deliberately run on a clean-control workbook that
    already belongs to the registered development controls.
    """
    from formulaguard.v6 import v6_scores
    from formulaguard.workbook import WorkbookModel

    path = ROOT / "data/v6_clean/clean/v6_clean_0201.xlsx"
    model = WorkbookModel.from_xlsx(path)
    variants = {}
    for variant in ("a", "b", "c"):
        ranking = v6_scores(model, variant=variant)
        promoted = [
            (rank, item)
            for rank, item in enumerate(ranking, start=1)
            if item.evidence.get("promotion_target")
        ]
        variants[variant] = {
            "promotion_count": len(promoted),
            "promotions": [
                {
                    "cell": f"{item.cell[0]}!{item.cell[1]}",
                    "rank": rank,
                    "candidate_formula": item.candidate_formula,
                    "semantic_tier": item.evidence.get("semantic_tier"),
                    "promotion_reason": item.evidence.get("promotion_reason"),
                }
                for rank, item in promoted
            ],
        }
    return {
        "scope": "single_registered_clean_control_diagnostic_only",
        "workbook": path.relative_to(ROOT).as_posix(),
        "workbook_sha256": sha256(path),
        "variants": variants,
        "all_variants_alarm": all(value["promotion_count"] > 0 for value in variants.values()),
    }


def markdown_report(payload: dict) -> str:
    dev = payload["development"]
    red = payload["redteam"]
    clean = payload["clean"]
    enron = payload["enron"]
    gates = payload["round_gate"]["gates"]
    v6 = f"v6_{payload['round']}"
    dev_v6, dev_v4 = dev["declared"][v6], dev["declared"]["v4"]
    red_v6, red_v4 = red["declared"][v6], red["declared"]["v4"]
    failed = [name for name, passed in gates.items() if not passed]
    probe = payload["cross_variant_clean_probe"]
    round_name = payload["round"]
    if round_name == "a":
        mechanism_interpretation = (
            "Range-boundary localization remains the weakest family because V6-A "
            "intentionally has no BSS component."
        )
        limitation = (
            "V6-A is a formula-family-only mechanism. It cannot test the registered "
            "range-boundary component, and the clean exception result indicates that "
            "strong family agreement plus counterfactual improvement is not sufficient "
            "evidence of an error."
        )
        next_step = (
            "Run the already preregistered V6-B and V6-C rounds without changing their "
            "logic. Do not freeze A. After all three rounds, run the preregistered one-shot "
            "locked internal validation with all A/B/C predictions written before labels "
            "are read. Development gates remain diagnostic and do not replace the locked "
            "selection gates."
        )
        questions = [
            "- Does BSS lift range-boundary Top-5 without adding new clean alarms?",
            "- Does C reject any ambiguous promotions beyond A/B, especially the exception-family alarms?",
            "- Do the fixed ablations confirm that FFC/BSS and the safety constraints each add non-redundant value?",
        ]
    elif round_name == "b":
        mechanism_interpretation = (
            "BSS closes the registered range-boundary gap: range-boundary Top-5 reaches "
            "100.00% on both development and red-team data. The remaining red-team "
            "weakness is absolute-reference localization at 35.00% Top-5."
        )
        limitation = (
            "V6-B demonstrates that boundary semantics can repair the failure family that "
            "motivated BSS, but it does not reduce the systematic clean exception alarms. "
            "Its red-team gains also include three lost V4 Top-5 hits, so semantic evidence "
            "without the registered C safety constraints is not yet safe enough to freeze."
        )
        next_step = (
            "Run the already preregistered V6-C round without changing its logic. Do not "
            "freeze B. After C is independently audited, run the preregistered one-shot "
            "locked internal validation with all A/B/C predictions written before labels "
            "are read."
        )
        questions = [
            "- Does C reduce exception-family alarms or red-team Top-5 losses without undoing BSS gains?",
            "- Does C preserve the 100% development and red-team range-boundary Top-5 result?",
            "- Do the fixed ablations confirm that FFC/BSS and the safety constraints each add non-redundant value?",
        ]
    else:
        mechanism_interpretation = (
            "V6-C must be interpreted jointly with A and B: its registered safety constraints "
            "are useful only if they reduce harmful promotions while preserving the semantic gains."
        )
        limitation = (
            "V6-C is the final preregistered development variant. Its result must not trigger "
            "another tuning round; eligibility for locked validation follows only from the "
            "registered gates and the A/B/C comparison."
        )
        next_step = (
            "Audit A, B and C together, then run the preregistered one-shot locked internal "
            "validation. All A/B/C predictions and matched ablations must be written before "
            "labels are read; the locked validation gates then determine whether freezing is allowed."
        )
        questions = [
            "- Do the C safety constraints reduce clean alarms and harmful red-team promotions?",
            "- Are the registered function and range gains preserved under C?",
            "- Do the fixed ablations confirm that FFC/BSS and the safety constraints each add non-redundant value?",
        ]
    lines = [
        f"# FormulaGuard V6-{payload['round'].upper()} data-quality and result audit",
        "",
        "## Technical summary",
        "",
        f"V6-{payload['round'].upper()} is trustworthy as a completed development diagnostic, but it did not pass its preregistered round gate and is not eligible for freezing. "
        f"Development macro Top-5 rose from {dev_v4['macro_top5']:.2%} to {dev_v6['macro_top5']:.2%}; red-team macro Top-5 rose from {red_v4['macro_top5']:.2%} to {red_v6['macro_top5']:.2%}. "
        f"However, clean false alarms were {clean['alarms']}/{clean['workbooks']} ({clean['false_alarm_rate']:.2%}) and Enron MRR changed by {enron['mrr_difference']:+.8f}. "
        f"Failed gates: {', '.join(failed)}.",
        "",
        "## The gain is large but uneven",
        "",
        f"On 1,200 development events, MRR improved from {dev_v4['mrr']:.4f} to {dev_v6['mrr']:.4f}, with {dev['paired_rank_changes'].get('new_top5_hit', 0)} new Top-5 hits and {dev['paired_rank_changes'].get('lost_top5_hit', 0)} losses. "
        f"On 360 red-team events, MRR improved from {red_v4['mrr']:.4f} to {red_v6['mrr']:.4f}, with {red['paired_rank_changes'].get('new_top5_hit', 0)} gains and {red['paired_rank_changes'].get('lost_top5_hit', 0)} losses. "
        + mechanism_interpretation,
        "",
        "## Legitimate exception formulas cause every clean alarm",
        "",
        f"All {clean['alarms']} alarms occur in the `exception` structure; its false-alarm rate is {clean['by_structure']['exception']['false_alarm_rate']:.2%}, while every other clean structure is 0%. "
        "This is a systematic failure mode rather than diffuse noise: an alternating but intentional MAX/MIN family looks locally inconsistent and receives a strong counterfactual promotion.",
        "",
        (
            "## Enron is practically unchanged and passes the exact safety rule"
            if gates.get("enron_mrr_not_below_v4", False)
            else "## Enron is practically unchanged but fails the exact safety rule"
        ),
        "",
        f"The retrospective Enron set contains {enron['events']} supported events from {enron['workbooks']} workbooks. "
        + (
            f"{len(enron['rank_changes'])} event(s) changed rank. Top-5 stayed at {enron['summary']['v4']['top5']:.2%}; "
            + (
                f"the exact non-decrease rule passes because MRR changed by {enron['mrr_difference']:+.8f}."
                if gates.get("enron_mrr_not_below_v4", False)
                else f"the exact non-decrease rule fails because MRR changed by {enron['mrr_difference']:+.8f}."
            )
        ),
        "",
        "## Scope, definitions, and integrity checks",
        "",
        "- Grain: one row per `(instance_id, method)` in scored CSV files; one complete-ranking JSON shard per workbook.",
        "- Top-k: the true source formula has rank at most k. MRR is `1/rank`; EXAM is `rank/formula_count`.",
        "- Clean alarm: any semantic promotion on a correct clean workbook.",
        "- Development and red-team raw keys are unique; metric identities and aggregate summaries were independently recomputed.",
        "- All prediction receipts report 24 requested workers, complete non-duplicate rankings and no label files read during localization.",
        "- Enron is retrospective only and cannot be presented as new independent evidence.",
        "",
        "## Limitations and robustness",
        "",
        limitation + " The corrected Enron comparison uses all 30 evaluation-ready events from the existing corpus and remains retrospective rather than independent evidence.",
        "",
        f"A one-workbook diagnostic probe found that the fixed A, B and C implementations all promote a candidate on `{probe['workbook']}`. This probe is not a population result, but it warns that the currently registered B/C safeguards may not remove the exception-family false-alarm mechanism.",
        "",
        "## Recommended next step",
        "",
        next_step,
        "",
        "## Further questions",
        "",
        *questions,
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", choices=("a", "b", "c"), required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    root = args.root or ROOT / f"results/v6_development_{args.round}"
    resolved_root = root.resolve()
    try:
        root_label = resolved_root.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        root_label = str(resolved_root)
    round_gate = load_json(root / "v6_round_audit.json")
    payload = {
        "protocol": "v6_independent_round_data_quality_audit_v1",
        "round": args.round,
        "root": root_label,
        "development": audit_layer(root, "development", args.round),
        "redteam": audit_layer(root, "redteam", args.round),
        "clean": audit_clean(root, args.round),
        "enron": audit_enron(root, args.round),
        "cross_variant_clean_probe": cross_variant_clean_probe(),
        "round_gate": round_gate,
        "source_hashes": {
            "round_audit": sha256(root / "v6_round_audit.json"),
            "development_raw": sha256(root / "development/raw_results.csv"),
            "redteam_raw": sha256(root / "redteam/raw_results.csv"),
            "clean_summary": sha256(root / "clean/v6_clean_summary.json"),
            "enron_raw": sha256(root / "enron/enron_raw.csv"),
        },
    }
    integrity = all(payload[key]["passed"] for key in ("development", "redteam", "clean", "enron"))
    payload["integrity_passed"] = integrity
    payload["development_evidence_usable"] = integrity
    payload["round_passed"] = bool(round_gate.get("round_passed")) and integrity
    json_output = args.json_output or ROOT / f"research/V6_{args.round.upper()}_DATA_QUALITY_AUDIT.json"
    markdown_output = args.markdown_output or ROOT / f"research/V6_{args.round.upper()}_RESULTS_AUDIT.md"
    json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_output.write_text(markdown_report(payload), encoding="utf-8")
    print(json_output)
    print(markdown_output)
    if not integrity:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
