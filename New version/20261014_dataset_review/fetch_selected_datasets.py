"""Download third-party source packages without opening labels in the model."""

import hashlib
import json
import subprocess
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ARCHIVES = BASE / "archives"
API = "https://api.github.com/repos/microsoft/prose-benchmarks/contents/FoRepBench/dataset"
REF = "d17e278092c59ec6faaa2d88730bdcbe48bb95f2"
SOURCES = [
    ("modified_euses", "https://spreadsheets.sai.tugraz.at/wp-content/uploads/sites/3/benchmarks/EUSES_modified.zip", "EUSES_modified.zip"),
    ("info1", "https://spreadsheets.sai.tugraz.at/wp-content/uploads/sites/3/benchmarks/Info1.zip", "Info1.zip"),
    ("integer", "https://spreadsheets.sai.tugraz.at/wp-content/uploads/sites/3/benchmarks/Integer.zip", "Integer.zip"),
    ("forepbench_dataset_listing", API + "?ref=" + REF, "FoRepBench_dataset_listing.json"),
]
EXTRA_SOURCES = [
    ("payroll_gradebook", "https://spreadsheets.sai.tugraz.at/wp-content/uploads/sites/3/benchmarks/Payroll_Gradebook.zip", "Payroll_Gradebook.zip"),
    ("forepbench_data_blob", "https://api.github.com/repos/microsoft/prose-benchmarks/git/blobs/7ccf5420923759637fff3009492b7e46d5077b39", "FoRepBenchmarks_blob.json"),
    ("forepbench_seed_blob", "https://api.github.com/repos/microsoft/prose-benchmarks/git/blobs/68418fe9c1bd896cc3c521243eea9d1bb59de2a1", "FoRepBench_seed_blob.json"),
]


def retrieve(item):
    name, url, filename = item
    destination = ARCHIVES / filename
    partial = ARCHIVES / (filename + ".partial")
    if destination.exists():
        raise FileExistsError(destination)
    proc = subprocess.run(
        ["curl", "--location", "--fail", "--silent", "--show-error",
         "--connect-timeout", "12", "--max-time", "55", "--max-filesize", "83886080",
         "--output", str(partial), "--write-out", "%{http_code}", url],
        capture_output=True, text=True,
    )
    success = proc.returncode == 0 and partial.is_file() and partial.stat().st_size > 0
    if success:
        partial.rename(destination)
    receipt = {
        "name": name, "url": url, "http_status": proc.stdout.strip(),
        "curl_exit_code": proc.returncode, "success": success,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "path": destination.relative_to(BASE).as_posix() if success else None,
        "size_bytes": destination.stat().st_size if success else None,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest() if success else None,
        "error": proc.stderr[-1000:],
    }
    print(name, receipt["http_status"], receipt["size_bytes"], flush=True)
    return receipt


def main(extra=False):
    ARCHIVES.mkdir(exist_ok=True)
    receipts = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(retrieve, item) for item in (EXTRA_SOURCES if extra else SOURCES)]):
            receipts.append(future.result())
    (BASE / ("EXTRA_PACKAGE_RECEIPTS.json" if extra else "PACKAGE_RECEIPTS.json")).write_text(
        json.dumps(receipts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--extra", action="store_true")
    main(parser.parse_args().extra)
