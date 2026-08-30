"""Run the repair-only and parser-stress audits without localization claims."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import FormulaSyntaxError, normalized_formula, parse_formula
from formulaguard.v5_psl import diagnose_v5_psl
from formulaguard.v5_psl_corpora import load_registry
from formulaguard.v5_psl_protocol import sha256
from formulaguard.workbook import WorkbookModel


def _forepbench(source: Path, expected_hash: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    candidates = list(source.rglob("FoRepBenchmarks.json"))
    if len(candidates) != 1:
        raise ValueError("FoRepBench role audit requires exactly one FoRepBenchmarks.json")
    dataset = candidates[0]
    if sha256(dataset) != expected_hash:
        raise ValueError("FoRepBench dataset differs from the pinned content hash")
    payload = json.loads(dataset.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("FoRepBench dataset must contain a JSON list")
    rows = []
    for index, item in enumerate(payload, 1):
        faulty = str(item.get("faulty_formula", "")) if isinstance(item, dict) else ""
        correct = str(item.get("correct_formula", "")) if isinstance(item, dict) else ""
        parseable_faulty = parseable_correct = True
        try:
            parse_formula(faulty)
        except (FormulaSyntaxError, ValueError):
            parseable_faulty = False
        try:
            parse_formula(correct)
        except (FormulaSyntaxError, ValueError):
            parseable_correct = False
        rows.append({
            "item_id": f"forepbench_{index:04d}",
            "task_scope": "repair_only",
            "formula_pair_present": int(bool(faulty and correct)),
            "formula_pair_distinct": int(
                bool(faulty and correct) and normalized_formula(faulty) != normalized_formula(correct)
            ),
            "faulty_formula_parseable": int(parseable_faulty),
            "correct_formula_parseable": int(parseable_correct),
            "runtime_error_labels_present": int(
                isinstance(item, dict) and bool(item.get("runtime_errors"))
            ),
            "localization_accuracy_eligible": 0,
        })
    audit = {
        "protocol": "v5_psl_supplemental_corpus_role_audit_v1",
        "corpus_id": "forepbench",
        "task_scope": "repair_only",
        "items": len(rows),
        "formula_pairs_present": sum(row["formula_pair_present"] for row in rows),
        "distinct_formula_pairs": sum(row["formula_pair_distinct"] for row in rows),
        "faulty_formula_parse_coverage": sum(row["faulty_formula_parseable"] for row in rows) / max(1, len(rows)),
        "correct_formula_parse_coverage": sum(row["correct_formula_parseable"] for row in rows) / max(1, len(rows)),
        "localization_accuracy_events": 0,
        "raw_data_redistributed": False,
        "complete": len(rows) == 618,
    }
    return rows, audit


def _safe_tar_members(path: Path) -> Iterator[tuple[str, bytes]]:
    with tarfile.open(path, "r:*") as archive:
        for member in archive.getmembers():
            relative = Path(member.name)
            if (
                not member.name or "\\" in member.name or relative.is_absolute()
                or ".." in relative.parts or member.issym() or member.islnk()
            ):
                raise ValueError(f"Unsafe SpreadsheetBench archive member: {member.name!r}")
            if not member.isfile() or relative.suffix.lower() != ".xlsx":
                continue
            if member.size > 250 * 1024 * 1024:
                raise ValueError(f"SpreadsheetBench workbook exceeds 250 MiB: {member.name}")
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError(f"Cannot read SpreadsheetBench workbook: {member.name}")
            yield member.name, handle.read()


def _spreadsheet_workbooks(source: Path) -> Iterator[tuple[str, Path | bytes]]:
    direct = sorted(path for path in source.rglob("*.xlsx") if path.is_file())
    for path in direct:
        yield path.relative_to(source).as_posix(), path
    archives = sorted({
        path for pattern in ("*.tar.gz", "*.tgz") for path in source.rglob(pattern)
        if path.is_file()
    })
    for archive in archives:
        prefix = archive.relative_to(source).as_posix()
        for name, data in _safe_tar_members(archive):
            yield f"{prefix}#{name}", data


def _spreadsheetbench(
    source: Path,
    *,
    limit: int | None,
    diagnose_limit: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows = []
    states: Counter[str] = Counter()
    formula_workbooks = 0
    diagnostic_attempts = 0
    diagnostic_failures = 0
    diagnose_cap = min(25, diagnose_limit)

    for index, (label, source_item) in enumerate(_spreadsheet_workbooks(source), 1):
        if limit is not None and index > limit:
            break
        parse_status = "parsed"
        diagnostic_state = "not_run"
        formula_count = 0
        error_type = ""
        try:
            if isinstance(source_item, Path):
                model = WorkbookModel.from_xlsx(source_item)
            else:
                with tempfile.TemporaryDirectory(prefix="spreadsheetbench_") as directory:
                    workbook_path = Path(directory) / "case.xlsx"
                    workbook_path.write_bytes(source_item)
                    model = WorkbookModel.from_xlsx(workbook_path)
            formula_count = len(model.formulas)
        except Exception as exc:
            parse_status = "excluded"
            diagnostic_state = "safe_skip"
            error_type = type(exc).__name__
        else:
            if formula_count:
                formula_workbooks += 1
            if formula_count and diagnostic_attempts < diagnose_cap:
                diagnostic_attempts += 1
                try:
                    report = diagnose_v5_psl(model)
                except Exception as exc:
                    diagnostic_state = "safe_skip"
                    diagnostic_failures += 1
                    error_type = type(exc).__name__
                else:
                    diagnostic_state = report.state.value
                    states[diagnostic_state] += 1
        rows.append({
            "item_id": f"spreadsheetbench_{index:04d}",
            "source_member": label,
            "task_scope": "parser_stress_only",
            "parse_status": parse_status,
            "formula_count": formula_count,
            "diagnostic_state": diagnostic_state,
            "exclusion_error_type": error_type,
            "localization_accuracy_eligible": 0,
        })
    if not rows:
        raise ValueError("SpreadsheetBench role audit found no actual .xlsx workbooks")
    parsed = sum(row["parse_status"] == "parsed" for row in rows)
    excluded = len(rows) - parsed
    diagnosed = sum(row["diagnostic_state"] not in {"not_run", "safe_skip"} for row in rows)
    diagnosis_target = min(25, formula_workbooks)
    limited = limit is not None or diagnose_limit < 25
    accounting_complete = parsed + excluded == len(rows)
    audit = {
        "protocol": "v5_psl_supplemental_corpus_role_audit_v1",
        "corpus_id": "spreadsheetbench",
        "task_scope": "parser_stress_only",
        "workbooks_attempted": len(rows),
        "parsed": parsed,
        "safe_skip_exclusions": excluded,
        "formula_workbooks": formula_workbooks,
        "diagnosis_target": diagnosis_target,
        "diagnosis_attempts": diagnostic_attempts,
        "diagnosed_without_labels": diagnosed,
        "diagnostic_failures": diagnostic_failures,
        "diagnostic_states": dict(sorted(states.items())),
        "accounting_complete": accounting_complete,
        "unhandled_crashes": 0,
        "localization_accuracy_events": 0,
        "limited": limited,
        "raw_data_redistributed": False,
        "complete": (
            accounting_complete
            and not limited
            and diagnosis_target > 0
            and diagnostic_attempts == diagnosis_target
            and diagnosed == diagnosis_target
            and diagnostic_failures == 0
        ),
    }
    return rows, audit


def _write(output: Path, rows: list[dict[str, object]], audit: dict[str, object]) -> None:
    output.mkdir(parents=True, exist_ok=False)
    with (output / "events.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    audit["events_sha256"] = sha256(output / "events.csv")
    (output / "role_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit V5-PSL supplemental corpus roles")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--corpus", choices=("forepbench", "spreadsheetbench"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--diagnose-limit", type=int, default=25)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.diagnose_limit < 1:
        parser.error("--diagnose-limit must be positive")
    try:
        registry = load_registry(args.registry.resolve())
        if args.corpus == "forepbench":
            if args.limit is not None:
                raise ValueError("FoRepBench formal role audit cannot be limited")
            expected = registry["forepbench"]["content_hashes"][
                "FoRepBench/dataset/FoRepBenchmarks.json"
            ]
            rows, audit = _forepbench(args.source.resolve(), str(expected))
        else:
            rows, audit = _spreadsheetbench(
                args.source.resolve(), limit=args.limit, diagnose_limit=args.diagnose_limit,
            )
        _write(args.output.resolve(), rows, audit)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, tarfile.TarError) as exc:
        raise SystemExit(f"V5-PSL supplemental corpus audit refused: {exc}") from exc
    print(args.output / "role_audit.json")


if __name__ == "__main__":
    main()
