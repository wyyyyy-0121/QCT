#!/usr/bin/env python3
"""Search commit metadata and inspect changed paths; never fetch workbook blobs."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "source_evidence"
RAW = OUT / "raw/natural_search"
RECEIPT = OUT / "NATURAL_REVISION_SEARCH.json"
QUERIES = ['"corrected formula" xlsx', '"formula error" spreadsheet', '"fix formula" xlsm']


def request_json(url, name):
    row = dict(url=url, name=name, acquired_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HybridGuard-source-audit/1.0",
                                                   "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=25) as response:
            body = response.read(5000001)
            row.update(status=response.status, resolved_url=response.url)
        assert len(body) <= 5000000
        path = RAW / (name + ".json")
        path.write_bytes(body)
        row.update(ok=True, sha256=hashlib.sha256(body).hexdigest())
        return row, json.loads(body)
    except Exception as error:
        row.update(ok=False, error=type(error).__name__ + ": " + str(error))
        return row, {}


def main():
    if RECEIPT.exists():
        raise SystemExit("Preserve search receipt")
    RAW.mkdir(parents=True)
    requests = []
    candidates = {}
    for index, query in enumerate(QUERIES):
        row, payload = request_json("https://api.github.com/search/commits?" +
            urllib.parse.urlencode({"q": query, "per_page": 10}), f"query_{index}")
        row["query"] = query
        row["total_count"] = payload.get("total_count")
        requests.append(row)
        for item in payload.get("items", []):
            repo = item["repository"]["full_name"]
            key = (repo, item["sha"])
            candidates[key] = dict(origin=repo, sha=item["sha"],
                message=item["commit"]["message"], url=item["url"])

    def detail(pair):
        index, candidate = pair
        receipt, payload = request_json(candidate["url"], f"commit_{index}")
        candidate = dict(candidate)
        candidate["request"] = receipt
        candidate["changed_workbook_paths"] = [dict(filename=item["filename"],
            status=item["status"], sha=item.get("sha"), previous_filename=item.get("previous_filename"))
            for item in payload.get("files", [])
            if item["filename"].lower().endswith((".xlsx", ".xlsm", ".xls", ".ods"))]
        candidate["parents"] = [parent["sha"] for parent in payload.get("parents", [])]
        candidate["natural_error_truth_certified"] = False
        candidate["workbook_bodies_acquired"] = False
        return candidate

    with ThreadPoolExecutor(max_workers=4) as pool:
        details = list(pool.map(detail, enumerate(list(candidates.values())[:18])))
    payload = {"queries": requests, "commit_candidates": details,
               "candidate_commits_with_changed_workbooks": sum(bool(c["changed_workbook_paths"]) for c in details),
               "accepted_natural_pairs": 0, "accepted_final_sources": 0,
               "notes": "Commit prose is a lead, not truth. All viewed author messages are recorded as prior exposure; inspect lineage, license and original/corrected formulas before any use."}
    RECEIPT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
