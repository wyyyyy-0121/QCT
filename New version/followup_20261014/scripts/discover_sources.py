"""Record public source metadata only; do not acquire final workbooks or labels."""
from pathlib import Path
import concurrent.futures
import datetime
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "source_discovery"
QUERIES = [
    "spreadsheet formula error dataset",
    "spreadsheet error corpus",
    "financial model xlsx",
    "LCOE excel",
    "cost benefit analysis spreadsheet",
    "project finance excel model",
    "spreadsheet auditing dataset",
    "spreadsheet formula repair benchmark",
]
PAGES = {
    "damodaran_models": "https://pages.stern.nyu.edu/~adamodar/spreads.htm",
    "nrel_cost_energy": "https://www.nrel.gov/analysis/tech-lcoe.html",
    "green_book": "https://www.gov.uk/government/publications/the-green-book-appraisal-and-evaluation-in-central-government",
    "world_bank_ppp_risk": "https://ppp.worldbank.org/public-private-partnership/library/ppp-fiscal-risk-assessment-model-p-fram",
    "spreadsheetbench2_readme": "https://raw.githubusercontent.com/RUCKBReasoning/SpreadsheetBench-2/main/README.md",
    "spreadsheet_error_dataset_readme": "https://raw.githubusercontent.com/YakZhang/Spreadsheet-Error-Dataset/main/README.md",
    "spreadnala_readme": "https://raw.githubusercontent.com/sebschu/SpreadNaLa/main/README.md",
}


def get(task):
    name, url = task
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    request = urllib.request.Request(url, headers={"User-Agent": "HybridGuard-research-source-audit/1.0", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            body = response.read(5_000_001)
            if len(body) > 5_000_000:
                raise ValueError("Metadata response exceeds limit")
            final_url, status = response.url, response.status
        path = OUT / "receipts" / (name + ".source")
        path.write_bytes(body)
        result = {"name": name, "url": url, "final_url": final_url, "utc": started, "status": status,
                  "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "path": str(path.relative_to(ROOT)), "ok": True}
        if name.startswith("github_search_"):
            data = json.loads(body)
            result["repositories"] = [{"repository": r["full_name"], "description": r.get("description"),
                "url": r["html_url"], "default_branch": r["default_branch"]} for r in data.get("items", [])]
        return result
    except Exception as error:
        return {"name": name, "url": url, "utc": started, "ok": False, "error": str(error)}


def main():
    (OUT / "receipts").mkdir(parents=True, exist_ok=True)
    path = OUT / "discovery_receipt.json"
    if path.exists():
        raise SystemExit("Discovery receipt exists; use a new version for a new acquisition.")
    tasks = list(PAGES.items()) + [("github_search_" + str(i),
        "https://api.github.com/search/repositories?q=" + urllib.parse.quote(query) + "&per_page=15")
        for i, query in enumerate(QUERIES)]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for result in executor.map(get, tasks):
            results.append(result)
            print(result["name"], "OK" if result["ok"] else result["error"], flush=True)
            if "repositories" in result:
                for row in result["repositories"]:
                    print(" ", row["repository"], row["description"], flush=True)
    path.write_text(json.dumps({"purpose": "metadata-only candidate discovery; not accepted validation sources",
        "final_workbooks_acquired": False, "queries": QUERIES, "receipts": results}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
