"""Download a small, receipt-backed candidate sample for development auditing.

This is deliberately not final validation acquisition.  The report records
transport integrity, workbook structure and formula fingerprints only.  It
does not read labels, errata, answer files or select a final test set.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
RAW = REPO / "data" / "external" / "hybridguard_candidate_audit_dev1" / "workbooks"
OUT = ROOT / "development" / "public_candidate_audit_dev7"

# The sample spans the seven origin groups already identified by the index
# audit.  Names are discovery labels, not verified independent families.
SAMPLES = [
    ("iowa_state_agdm", "hay_budget", "https://www.extension.iastate.edu/agdm/crops/xls/a1-15-20haybudgetonly.xlsx"),
    ("iowa_state_agdm", "crop_rotation", "https://www.extension.iastate.edu/agdm/crops/xls/a1-20croprotation.xlsx"),
    ("iowa_state_agdm", "farm_finance", "https://www.extension.iastate.edu/agdm/wholefarm/xls/c3-14cashflowbudget12month.xlsx"),
    ("damodaran", "capital_structure", "https://pages.stern.nyu.edu/~adamodar/pc/capstru.xlsx"),
    ("damodaran", "fcff_simple", "https://pages.stern.nyu.edu/~adamodar/pc/fcffsimpleginzu.xlsx"),
    ("epa", "refrigerated_condenser", "https://www.epa.gov/sites/default/files/2017-12/refrigerated_condenser_calc_sheet_2017.xlsm"),
    ("epa", "carbon_adsorber", "https://www.epa.gov/sites/default/files/2020-11/epa_carbon_adsorber_calc_sheet_7thedition_nov2020.xlsm"),
    ("uk_government", "lcoe_calculator", "https://assets.publishing.service.gov.uk/media/64f19bbf9ee0f2000fb7bd53/Annex_B_-_Example_LCOE_calculator_correction_20230831.xlsx"),
    ("18f", "software_model", "https://raw.githubusercontent.com/18F/financial-models/d86e8f89145bb0e29cd7268e1497de45ddbae0c8/Software%20Model.xlsx"),
    ("packt", "financial_model", "https://raw.githubusercontent.com/PacktPublishing/Project-Finance-and-Excel---Build-Financial-Models-from-Scratch/618787e67a7ee0e6643f60ef447a9c35d6ee9301/Financial%2BModel.xlsx"),
    ("renewables", "simplified_project_finance", "https://raw.githubusercontent.com/RenewablesPro/rvi-sample-models/1e49ec79613c77c3fa6f8532b4e303b473f85506/Simplified-Project-Finance-Model.xlsx"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_formula(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def formula_fingerprint(path: Path) -> dict:
    """Count and hash formulas without emitting their contents."""
    suffix = path.suffix.casefold()
    if suffix not in {".xlsx", ".xlsm"}:
        return {"status": "unsupported_container", "formula_cells": None}
    try:
        # XML-level inspection avoids recalculation and keeps large government
        # workbooks bounded.  Formula text is hashed, never written to the report.
        with zipfile.ZipFile(path) as archive:
            names = sorted(n for n in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
            formulas = []
            sheet_stats = []
            for name in names:
                raw = archive.read(name)
                values = re.findall(rb"<f(?:\s[^>]*)?>(.*?)</f>", raw, flags=re.S)
                count = len(values)
                formulas.extend(normalize_formula(v.decode("utf-8", "replace")) for v in values)
                sheet_stats.append({"xml_name": name, "formula_cells": count,
                                    "xml_bytes": len(raw)})
        formulas.sort()
        return {
            "status": "parsed",
            "sheet_count": len(sheet_stats),
            "sheet_stats": sheet_stats,
            "formula_cells": len(formulas),
            "formula_fingerprint_sha256": hashlib.sha256("\n".join(formulas).encode()).hexdigest(),
        }
    except Exception as exc:  # retain failures as evidence, never drop them
        return {"status": "parse_failed", "formula_cells": None,
                "error": f"{type(exc).__name__}: {exc}"}


def acquire(origin: str, label: str, url: str) -> dict:
    suffix = Path(url.split("?", 1)[0]).suffix.casefold() or ".bin"
    target_dir = RAW / origin
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{label}{suffix}"
    row = {"origin": origin, "discovery_label": label, "url": url,
           "retrieved_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
           "final_validation_eligible": False, "path": str(target.relative_to(REPO))}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "HybridGuardCandidateAudit/1.0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            body_parts = []
            total = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > 25 * 1024 * 1024:
                    raise ValueError("candidate_exceeds_25MiB_limit")
                body_parts.append(block)
            body = b"".join(body_parts)
            target.write_bytes(body)
            row.update(status="downloaded", http_status=response.status,
                       effective_url=response.geturl(), bytes=len(body), sha256=sha256(target))
        row["structure"] = formula_fingerprint(target)
    except Exception as exc:
        row.update(status="acquisition_failed", error=f"{type(exc).__name__}: {exc}")
    return row


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"Preserve existing run: {OUT}")
    OUT.mkdir(parents=True)
    records = [acquire(*sample) for sample in SAMPLES]
    downloaded = [r for r in records if r["status"] == "downloaded"]
    by_sha = {}
    by_formula = {}
    for row in downloaded:
        by_sha.setdefault(row["sha256"], []).append(row["discovery_label"])
        fp = row.get("structure", {}).get("formula_fingerprint_sha256")
        if fp:
            by_formula.setdefault(fp, []).append(row["discovery_label"])
    report = {
        "role": "development candidate audit; not final validation",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sample_count": len(records),
        "downloaded_count": len(downloaded),
        "origin_groups_observed": sorted({r["origin"] for r in downloaded}),
        "records": records,
        "duplicate_file_sha256_groups": [v for v in by_sha.values() if len(v) > 1],
        "duplicate_formula_fingerprint_groups": [v for v in by_formula.values() if len(v) > 1],
        "accepted_sources": 0,
        "accepted_template_families": 0,
        "limits": [
            "A download and formula count do not establish license scope or source independence.",
            "Formula fingerprints are structural metadata, not correctness labels.",
            "No workbook is used for model selection, threshold tuning or final scoring.",
            "Natural-error truth and a clean-to-injected audit remain outstanding.",
        ],
    }
    (OUT / "REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (OUT / "README.md").write_text(
        "# Public candidate workbook audit (development)\n\n"
        "This run checks transport integrity and workbook structure for a small sample "
        "of already indexed public candidates. It is not a final-validation dataset; "
        "the raw files remain outside Git under `data/external/`.\n"
    )
    print(json.dumps({"downloaded": len(downloaded), "origins": report["origin_groups_observed"],
                      "duplicate_formula_groups": report["duplicate_formula_fingerprint_groups"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
