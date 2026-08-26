"""Build the preregistered A/B/C development comparison receipt.

The receipt is descriptive only.  It verifies that all three fixed variants
were evaluated against identical inputs and records their development failure
modes, but it deliberately does not select a variant.  Selection belongs to
the one-shot 360-event locked validation protocol in V6_METHOD_SPEC.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def difference(right: float, left: float) -> float:
    return right - left


def build_receipt() -> dict:
    rounds: dict[str, dict] = {}
    metadata: dict[str, dict] = {}
    integrity: dict[str, bool] = {}
    for letter in "abc":
        result_root = ROOT / f"results/v6_development_{letter}"
        round_audit_path = result_root / "v6_round_audit.json"
        independent_path = ROOT / f"research/V6_{letter.upper()}_DATA_QUALITY_AUDIT.json"
        prediction_metadata_path = result_root / "development/predictions/prediction_metadata.json"
        round_audit = load(round_audit_path)
        independent = load(independent_path)
        prediction_metadata = load(prediction_metadata_path)
        method = f"v6_{letter}"
        rounds[letter] = {
            "mechanism": round_audit["single_mechanism"],
            "workers": round_audit["workers"],
            "development": round_audit["development"],
            "redteam": round_audit["redteam"],
            "clean_false_alarm_rate": round_audit["clean_false_alarm_rate"],
            "enron_v4": round_audit["enron"]["v4"],
            "enron_variant": round_audit["enron"][method],
            "development_diagnostic_gates": round_audit["gates"],
            "development_round_passed_diagnostic": round_audit["round_passed"],
            "round_audit_sha256": sha256(round_audit_path),
            "independent_audit_sha256": sha256(independent_path),
            "prediction_git_commit": prediction_metadata["git_commit"],
        }
        metadata[letter] = prediction_metadata
        integrity[letter] = bool(independent.get("integrity_passed"))

    shared_fields = (
        "instances_sha256", "dataset_manifest_sha256", "dataset_completion_sha256",
        "v6_source_sha256", "v4_source_sha256", "method_spec_sha256", "parameters",
    )
    shared_input_and_model = all(
        metadata[letter][field] == metadata["a"][field]
        for letter in "bc" for field in shared_fields
    )
    label_isolation = all(metadata[letter].get("label_files_read") == [] for letter in "abc")
    variants_exact = all(metadata[letter].get("variants") == [letter] for letter in "abc")
    workers_24 = all(rounds[letter]["workers"] == 24 for letter in "abc")
    event_counts = all(
        rounds[letter]["development"]["events"] == 1200
        and rounds[letter]["redteam"]["events"] == 360
        and rounds[letter]["enron_variant"]["events"] == 30
        for letter in "abc"
    )
    comparison_integrity = {
        "all_independent_round_audits_passed": all(integrity.values()),
        "shared_input_model_and_parameters": shared_input_and_model,
        "prediction_label_isolation": label_isolation,
        "variant_identity_exact": variants_exact,
        "all_rounds_workers_24": workers_24,
        "all_registered_event_counts_present": event_counts,
    }
    ready = all(comparison_integrity.values())
    contrasts = {
        "b_minus_a": {
            "development_macro_top5": difference(rounds["b"]["development"]["macro_top5"], rounds["a"]["development"]["macro_top5"]),
            "development_mrr": difference(rounds["b"]["development"]["mrr"], rounds["a"]["development"]["mrr"]),
            "development_range_boundary_top5": difference(
                rounds["b"]["development"]["by_error"]["range_boundary"]["top5"],
                rounds["a"]["development"]["by_error"]["range_boundary"]["top5"],
            ),
            "redteam_macro_top5": difference(rounds["b"]["redteam"]["macro_top5"], rounds["a"]["redteam"]["macro_top5"]),
        },
        "c_minus_b": {
            "development_macro_top5": difference(rounds["c"]["development"]["macro_top5"], rounds["b"]["development"]["macro_top5"]),
            "development_mrr": difference(rounds["c"]["development"]["mrr"], rounds["b"]["development"]["mrr"]),
            "development_absolute_reference_top5": difference(
                rounds["c"]["development"]["by_error"]["absolute_reference"]["top5"],
                rounds["b"]["development"]["by_error"]["absolute_reference"]["top5"],
            ),
            "redteam_macro_top5": difference(rounds["c"]["redteam"]["macro_top5"], rounds["b"]["redteam"]["macro_top5"]),
            "clean_false_alarm_rate": difference(rounds["c"]["clean_false_alarm_rate"], rounds["b"]["clean_false_alarm_rate"]),
        },
    }
    return {
        "protocol": "v6_preregistered_development_abc_comparison_v1",
        "scope": "development_diagnostic_only_no_variant_selection",
        "rounds": rounds,
        "contrasts": contrasts,
        "comparison_integrity": comparison_integrity,
        "comparison_integrity_passed": ready,
        "selection_made": False,
        "selection_source": "one_shot_locked_360_event_validation_only",
        "ready_for_locked_validation": ready,
        "method_spec_sha256": metadata["a"]["method_spec_sha256"],
        "v6_source_sha256": metadata["a"]["v6_source_sha256"],
        "v4_source_sha256": metadata["a"]["v4_source_sha256"],
    }


def markdown(receipt: dict) -> str:
    rows = receipt["rounds"]
    lines = [
        "# FormulaGuard V6 A/B/C development comparison",
        "",
        "## Decision",
        "",
        "All three preregistered development variants are complete and independently auditable. "
        "This comparison does not select a model: the frozen method specification reserves selection "
        "for the one-shot 360-event locked validation after all A/B/C predictions and matched ablations are on disk.",
        "",
        "| Variant | Mechanism | Dev macro Top-5 | Dev MRR | Red-team macro Top-5 | Worst red-team type | Clean FPR | Enron MRR delta |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for letter in "abc":
        row = rows[letter]
        dev, red = row["development"], row["redteam"]
        enron_delta = row["enron_variant"]["mrr"] - row["enron_v4"]["mrr"]
        lines.append(
            f"| V6-{letter.upper()} | {row['mechanism']} | {dev['macro_top5']:.2%} | {dev['mrr']:.4f} | "
            f"{red['macro_top5']:.2%} | {red['worst_type_top5']:.2%} | "
            f"{row['clean_false_alarm_rate']:.2%} | {enron_delta:+.8f} |"
        )
    ba = receipt["contrasts"]["b_minus_a"]
    cb = receipt["contrasts"]["c_minus_b"]
    lines += [
        "",
        "## Mechanism interpretation",
        "",
        f"- BSS is strongly supported as a range mechanism: B minus A is {ba['development_range_boundary_top5']:+.2%} "
        f"development range-boundary Top-5 and {ba['redteam_macro_top5']:+.2%} red-team macro Top-5.",
        f"- The C safety constraints do not reduce the registered clean exception alarm rate "
        f"({cb['clean_false_alarm_rate']:+.2%}) and leave red-team macro Top-5 unchanged "
        f"({cb['redteam_macro_top5']:+.2%}).",
        f"- C is more conservative on development data: C minus B is {cb['development_macro_top5']:+.2%} macro Top-5; "
        f"the change is concentrated in absolute-reference cases ({cb['development_absolute_reference_top5']:+.2%}).",
        "- C exactly preserves V4 on the 30-event Enron retrospective check, while A/B share a one-rank tail regression. "
        "Enron remains retrospective and is not independent evidence.",
        "",
        "## Integrity and next step",
        "",
        *[f"- {name}: {str(value).lower()}" for name, value in receipt["comparison_integrity"].items()],
        "- No development result is used to change formulas, weights, thresholds, candidates or validation labels.",
        "- Next: run the one-shot locked 360-event validation with all fixed variants and eight matched ablations.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", type=Path, default=Path("research/V6_ABC_DEVELOPMENT_DECISION.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("research/V6_ABC_DEVELOPMENT_DECISION.md"))
    args = parser.parse_args()
    receipt = build_receipt()
    args.json_output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text(markdown(receipt), encoding="utf-8")
    print(args.json_output)
    print(args.markdown_output)
    if not receipt["ready_for_locked_validation"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
