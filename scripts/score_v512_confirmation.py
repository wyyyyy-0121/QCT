"""Strict V5.1.2 scoring: actual groups, global unsafe actions, bound shards.

Only fully adjudicated synthetic labels can support repair/safety metrics.
Real corpora with incomplete truth must be reported separately as localization
diagnostics; absence from their known-error list does not mean a cell is clean.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(root: Path, name: str) -> Path:
    portable = PurePosixPath(name)
    if not name or portable.is_absolute() or ".." in portable.parts or "\\" in name or ":" in name:
        raise ValueError("unsafe relative path")
    path = (root / name).resolve()
    if root.resolve() not in path.parents:
        raise ValueError("path escapes root")
    return path


def canonical_formula(formula: str) -> str:
    # AST normalization preserves constants and quoted text semantics. Unsupported
    # syntax uses exact text; no unsafe whitespace removal within string literals.
    from formulaguard.a1 import parse_address
    from formulaguard.formula import fingerprint, parse_formula
    try:
        return fingerprint(parse_formula(formula), parse_address("A1"))
    except ValueError:
        return formula.strip()


def verify_run(root: Path, expected_lock_sha: str, expected_cases: dict) -> dict:
    if sha256(root / "prediction_lock.json") != expected_lock_sha:
        raise ValueError("prediction lock hash mismatch")
    lock = json.loads((root / "prediction_lock.json").read_text())
    if lock.get("protocol") != "v512_prediction_lock_v1" or lock.get("labels_read") != []:
        raise ValueError("invalid prediction protocol or label access")
    if lock.get("cases") != len(expected_cases):
        raise ValueError("case count mismatch")
    if sha256(root / "prediction_metadata.json") != lock["metadata_sha256"]:
        raise ValueError("metadata hash mismatch")
    metadata = json.loads((root / "prediction_metadata.json").read_text())
    if metadata.get("labels_read") != [] or metadata.get("model") != lock.get("model"):
        raise ValueError("invalid prediction metadata")
    actual = {p.relative_to(root).as_posix() for p in (root / "shards").rglob("*") if p.is_file()}
    if actual != set(lock["shards"]):
        raise ValueError("missing or extra prediction shard")
    shards = {}
    for relative, expected_sha in lock["shards"].items():
        path = safe_path(root, relative)
        if sha256(path) != expected_sha:
            raise ValueError("prediction shard hash mismatch")
        shard = json.loads(path.read_text())
        case = shard["case_id"]
        if case in shards or case not in expected_cases:
            raise ValueError("duplicate or unknown case")
        if shard["workbook_sha256"] != expected_cases[case]["workbook_sha256"]:
            raise ValueError("workbook identity mismatch")
        if shard["model"] != lock["model"]:
            raise ValueError("shard model mismatch")
        validate_ranking(shard, expected_cases[case].get("formula_cells"))
        shards[case] = shard
    if set(shards) != set(expected_cases):
        raise ValueError("incomplete predictions")
    return shards


def verify_double_run(root: Path, locks: dict, expected_cases: dict) -> dict:
    first = verify_run(root / "run_a", locks["run_a"], expected_cases)
    second = verify_run(root / "run_b", locks["run_b"], expected_cases)
    if first != second:
        raise ValueError("double-run prediction mismatch")
    return first


def validate_ranking(shard: dict, expected_cells=None) -> None:
    ranking = shard["ranking"]
    cells = [(r["sheet"], r["cell"]) for r in ranking]
    if len(cells) != len(set(cells)) or len(cells) != shard["formula_count"]:
        raise ValueError("duplicate or incomplete ranking")
    if expected_cells is not None and set(cells) != {tuple(c) for c in expected_cells}:
        raise ValueError("ranking differs from workbook formula cells")
    if [r["rank"] for r in ranking] != list(range(1, len(ranking) + 1)):
        raise ValueError("invalid rank sequence")
    if any(not math.isfinite(r["score"]) for r in ranking):
        raise ValueError("nonfinite score")


def score_case(shard: dict, label: dict) -> dict:
    if label.get("truth_completeness") != "complete":
        raise ValueError("repair/safety scoring requires complete truth")
    if shard["case_id"] != label["case_id"] or shard["workbook_sha256"] != label["workbook_sha256"]:
        raise ValueError("label identity mismatch")
    if label["decision"] not in {"detect_and_repair", "no_action", "abstain"}:
        raise ValueError("unknown decision")
    validate_ranking(shard)
    ranking = shard["ranking"]
    errors = {(e["sheet"], e["cell"]): canonical_formula(e["expected_formula"]) for e in label["errors"]}
    if len(errors) != len(label["errors"]):
        raise ValueError("duplicate truth cells")
    ranked_cells = {(r["sheet"], r["cell"]) for r in ranking}
    if not set(errors) <= ranked_cells:
        raise ValueError("truth cell absent from ranking")
    if label["decision"] == "detect_and_repair" and not errors:
        raise ValueError("repair case has no errors")
    if label["decision"] == "no_action" and errors:
        raise ValueError("clean control has error labels")
    groups = defaultdict(list)
    candidates = []
    exact = set()
    truth_hits = 0
    ap_total = 0.0
    for rank, item in enumerate(ranking, 1):
        cell = (item["sheet"], item["cell"])
        if cell in errors:
            truth_hits += 1
            ap_total += truth_hits / rank
        candidate = item["candidate_formula"]
        evidence = item.get("evidence", {})
        if candidate is not None:
            if not isinstance(candidate, str) or not candidate.startswith("="):
                raise ValueError("invalid candidate formula")
            candidates.append(cell)
            if cell in errors and canonical_formula(candidate) == errors[cell]:
                exact.add(cell)
        if evidence.get("group_state") == "accepted":
            if candidate is None or not evidence.get("group_id"):
                raise ValueError("accepted member missing formula/group identity")
            groups[evidence["group_id"]].append(item)
    if shard.get("accepted_group_count") != len(groups):
        raise ValueError("declared group count differs from actual groups")
    correct_groups = 0
    accepted_cells = set()
    for members in groups.values():
        if any(m["evidence"].get("group_size") != len(members) for m in members):
            raise ValueError("declared group size differs from actual membership")
        cells = {(m["sheet"], m["cell"]) for m in members}
        accepted_cells |= cells
        correct_groups += int(label["decision"] == "detect_and_repair" and cells <= exact)
    return {
        "case_id": label["case_id"], "cluster_id": label["cluster_id"],
        "family": label["family"], "cohort": label["cohort"], "decision": label["decision"],
        "errors": len(errors), "average_precision": ap_total / len(errors) if errors else None,
        "candidate_count": len(candidates), "candidate_truth_hits": len(set(candidates) & set(errors)),
        "exact_repairs": len(exact), "accepted_cells": len(accepted_cells),
        "accepted_exact_cells": len(accepted_cells & exact),
        "accepted_groups": len(groups), "exact_groups": correct_groups,
        "unsafe_groups": len(groups) - correct_groups,
    }


def summarize(rows: list[dict]) -> dict:
    def rate(n, d):
        return n / d if d else None
    repair = [r for r in rows if r["decision"] == "detect_and_repair"]
    controls = [r for r in rows if r["decision"] == "no_action"]
    ambiguous = [r for r in rows if r["decision"] == "abstain"]
    errors = sum(r["errors"] for r in repair)
    groups = sum(r["accepted_groups"] for r in rows)
    return {
        "cases": len(rows), "repair_cases": len(repair), "error_cells": errors,
        "repair_macro_ap": rate(sum(r["average_precision"] for r in repair), len(repair)),
        "exact_candidate_coverage": rate(sum(r["exact_repairs"] for r in repair), errors),
        "global_candidate_location_precision": rate(sum(r["candidate_truth_hits"] for r in repair), sum(r["candidate_count"] for r in rows)),
        "global_exact_candidate_precision": rate(sum(r["exact_repairs"] for r in repair), sum(r["candidate_count"] for r in rows)),
        "accepted_cell_precision": rate(sum(r["accepted_exact_cells"] for r in repair), sum(r["accepted_cells"] for r in rows)),
        "accepted_group_precision": rate(sum(r["exact_groups"] for r in rows), groups),
        "accepted_group_count": groups,
        "unsafe_accepted_groups_all_workbooks": sum(r["unsafe_groups"] for r in rows),
        "unsafe_accepted_groups_in_repair_workbooks": sum(r["unsafe_groups"] for r in repair),
        "control_workbook_candidate_fpr": rate(sum(r["candidate_count"] > 0 for r in controls), len(controls)),
        "ambiguous_workbook_candidate_rate": rate(sum(r["candidate_count"] > 0 for r in ambiguous), len(ambiguous)),
    }
