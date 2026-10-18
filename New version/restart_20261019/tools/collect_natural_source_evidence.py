#!/usr/bin/env python3
"""Collect official errata for an already excluded development origin.

The documents identify historical defects; they are not paired workbook labels.
Workbook bodies reserved for final validation are never fetched here.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "source_evidence"
RAW = OUT / "raw"
RECEIPT = OUT / "EPA_ERRATA_RECEIPT.json"
SOURCES = {
    "carbon_adsorbers": "https://www.epa.gov/sites/production/files/2020-11/documents/erratasheet_carbonadsorbers_costcalcspreadsheet.pdf",
    "flares": "https://www.epa.gov/system/files/documents/2022-09/ErrataSheet_flares_cost%20calculationspreadsheetcorrections_September%202022.pdf",
    "oxidizers": "https://www.epa.gov/system/files/documents/2024-12/errata_sheet_incineratorsoxidizers_costcalculationspreadsheet_december2024.pdf",
}


def fetch(item):
    name, url = item
    row = dict(id=name, url=url, origin="US EPA", role="development natural-error provenance",
               final_validation_eligible=False, acquired_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HybridGuard-research-source-audit/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read(8000001)
            row.update(http_status=response.status, resolved_url=response.url)
        assert len(body) <= 8000000 and body.startswith(b"%PDF-"), "not a bounded PDF response"
        path = RAW / (name + ".pdf")
        with path.open("xb") as handle:
            handle.write(body)
        text = RAW / (name + ".txt")
        subprocess.run(["pdftotext", "-layout", str(path), str(text)], check=True, timeout=30)
        row.update(ok=True, bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                   text_sha256=hashlib.sha256(text.read_bytes()).hexdigest(),
                   original_workbook_acquired=False, paired_correct_formula_truth_certified=False)
    except Exception as error:
        row.update(ok=False, error=type(error).__name__ + ": " + str(error))
    return row


def main():
    if RECEIPT.exists():
        raise SystemExit("Preserve existing source receipts")
    RAW.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(fetch, SOURCES.items()))
    receipt = {"records": rows, "accepted_natural_pairs": 0,
               "accepted_final_sources": 0, "accepted_final_families": 0,
               "reason": "official errata provenance only; obtain historical defective original and certify formula mapping before scoring"}
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
