"""Audit the complete v3 research package without turning completeness into a win claim."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the evidence package for the FormulaGuard v3 paper")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when a required condition is absent")
    args = parser.parse_args()
    root = args.root.resolve()
    full = root / "results" / "v3_full"
    enron = root / "results" / "enron_test_v3_real"
    research = root / "research"
    checks: list[dict[str, Any]] = []

    def record(name: str, passed: bool, evidence: Any, *, required: bool = True) -> None:
        checks.append({"name": name, "passed": bool(passed), "required": required, "evidence": evidence})

    full_audit_path = full / "completion_audit.json"
    if full_audit_path.is_file():
        full_audit = load_json(full_audit_path)
        record("synthetic_full_completion", full_audit.get("evidence_complete") is True, {
            "valid_instances": full_audit.get("details", {}).get("valid_instances"),
            "valid_rate": full_audit.get("details", {}).get("valid_rate"),
            "audit_checks": full_audit.get("checks", {}),
        })
        record("synthetic_full_size", full_audit.get("details", {}).get("valid_instances", 0) >= 864,
               full_audit.get("details", {}).get("valid_instances"))
    else:
        record("synthetic_full_completion", False, f"missing: {full_audit_path}")
        record("synthetic_full_size", False, "synthetic completion audit unavailable")

    libre_path = full / "cross_engine_audit.json"
    if libre_path.is_file():
        libre = load_json(libre_path)
        record("libreoffice_cross_engine", libre.get("status") == "completed" and libre.get("mismatching_formula_values") == 0, {
            "workbooks": libre.get("workbooks"),
            "checked_formula_values": libre.get("checked_formula_values"),
            "mismatching_formula_values": libre.get("mismatching_formula_values"),
        })
    else:
        record("libreoffice_cross_engine", False, f"missing: {libre_path}")

    blind_path = enron / "blind_result_audit.json"
    external_dataset_path = enron / "external_dataset_audit.json"
    if blind_path.is_file() and external_dataset_path.is_file():
        blind = load_json(blind_path)
        dataset = load_json(external_dataset_path)
        integrity = blind.get("integrity", {})
        record("enron_blind_manifest_integrity", all((
            integrity.get("manifest_events") == 20,
            integrity.get("raw_rows") == 200,
            integrity.get("events_in_raw") == 20,
            integrity.get("manifest_hash_matches_freeze") is True,
            not integrity.get("duplicate_event_method_pairs"),
            not integrity.get("missing_event_method_pairs"),
        )), integrity)
        record("enron_quantitative_sample_size", dataset.get("quantitative_reporting_allowed") is True and dataset.get("evaluated_instances") >= 15, {
            "evaluated_instances": dataset.get("evaluated_instances"),
            "quantitative_reporting_allowed": dataset.get("quantitative_reporting_allowed"),
        })
        conclusion = blind.get("conclusion", {})
        record("enron_negative_conclusion_preserved", conclusion.get("stable_improvement_over_graph") is False, conclusion)
    else:
        record("enron_blind_manifest_integrity", False, "missing blind audit or external dataset audit")
        record("enron_quantitative_sample_size", False, "external dataset audit unavailable")
        record("enron_negative_conclusion_preserved", False, "blind conclusion unavailable")

    latency_csv = full / "performance_v3_latency.csv"
    latency_meta = full / "performance_v3_latency_metadata.json"
    if latency_csv.is_file() and latency_meta.is_file():
        rows = load_csv(latency_csv)
        metadata = load_json(latency_meta)
        sizes = sorted({int(row["target_formula_count"]) for row in rows})
        record("isolated_latency_protocol", all((
            metadata.get("measurement_mode") == "latency",
            metadata.get("workers") == 1,
            metadata.get("repeats") == 5,
            metadata.get("jobs") == 20,
            len(rows) == 20,
            sizes == [100, 500, 1000, 5000],
            all(row.get("measurement_mode") == "latency" and row.get("worker_count") == "1" for row in rows),
        )), {"rows": len(rows), "sizes": sizes, "metadata": metadata})
    else:
        record("isolated_latency_protocol", False, "latency CSV or metadata missing")

    throughput_csv = full / "performance_v3_throughput.csv"
    throughput_meta = full / "performance_v3_throughput_metadata.json"
    if throughput_csv.is_file() and throughput_meta.is_file():
        rows = load_csv(throughput_csv)
        metadata = load_json(throughput_meta)
        sizes = sorted({int(row["target_formula_count"]) for row in rows})
        record("parallel_throughput_protocol", all((
            metadata.get("measurement_mode") == "throughput",
            int(metadata.get("workers", 0)) > 1,
            metadata.get("repeats") == 5,
            metadata.get("jobs") == 20,
            len(rows) == 20,
            sizes == [100, 500, 1000, 5000],
            all(row.get("measurement_mode") == "throughput" and int(row.get("worker_count", 0)) > 1 for row in rows),
        )), {"rows": len(rows), "sizes": sizes, "metadata": metadata})
    else:
        record("parallel_throughput_protocol", False, "throughput CSV or metadata missing")

    document_paths = [
        research / "PAPER_BODY_DRAFT_V3.md",
        research / "PAPER_EVIDENCE_LEDGER_V3.md",
        research / "REFERENCES_V3.md",
        research / "AUTHENTICITY_AND_NOVELTY_PROTOCOL.md",
        research / "PERFORMANCE_MEASUREMENT_PROTOCOL.md",
        research / "frozen_config_v3_real.json",
        full / "figures" / "performance_latency.svg",
        full / "figures" / "performance_latency_table.md",
    ]
    record("paper_evidence_documents", all(path.is_file() for path in document_paths), [str(path.relative_to(root)) for path in document_paths if path.is_file()])

    ready = all(check["passed"] for check in checks if check["required"])
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "project_root": str(root),
        "ready_for_final_paper_package": ready,
        "checks": checks,
        "interpretation": (
            "A passing audit means required evidence and protocol boundaries are present. "
            "It does not mean FormulaGuard outperformed real-workbook baselines; the Enron negative conclusion remains required."
        ),
    }
    output = args.output or full / "v3_delivery_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = output.with_suffix(".md")
    lines = ["# FormulaGuard v3 最终交付审计", "", f"- 可进入最终论文包：`{ready}`", ""]
    for check in checks:
        marker = "通过" if check["passed"] else "未通过"
        lines.append(f"- **{check['name']}**：{marker}")
    lines += ["", "> 审计通过只证明证据和边界记录完整；它不改变 Enron 盲测未稳定优于图基线的结论。", ""]
    markdown.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict and not ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
