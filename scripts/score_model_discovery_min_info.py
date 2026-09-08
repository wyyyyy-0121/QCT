"""Measure the value of four minimal pieces of added debugging information.

Gate 2 rejected a safe successor under the no-output contract.  This branch-C
experiment therefore measures an explicit interactive contract instead of
searching more no-label signals.  The four conditions are fixed:

* ``history_version``: a verified previous workbook is supplied;
* ``key_output``: one visible output cell is supplied (the deterministic
  highest-ancestor sink is an offline proxy for that user choice);
* ``pass_fail``: the same output is marked failed or passed;
* ``domain_constraint``: one exact formula constraint is supplied for the
  first changed cell when a verified history exists.

The latter two reference the revealed case kind or paired workbook only to
simulate the information a user would provide.  They are not no-label model
results and are reported with their availability and burden explicitly.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.a1 import parse_address
from formulaguard.workbook import WorkbookModel

PROTOCOL = "formulaguard_model_discovery_branch_c_min_info_v1"
CONDITIONS = ("history_version", "key_output", "pass_fail", "domain_constraint")
REVIEW_BUDGET = 5
DEFAULT_GATE2 = ROOT / "results/model_discovery_gate2_final_v3"
DEFAULT_PROFILES = ROOT / "results/core_reset_b_phase0/observation_profiles.csv"
DEFAULT_PUBLIC_MANIFEST = ROOT / "results/v5_psl_pressure_inputs/public_pressure_manifest.csv"
DEFAULT_OUTPUT = ROOT / "results/model_discovery_branch_c"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def write_immutable(path: Path, data: bytes, *, description: str) -> None:
    """Create an output once, or verify that an existing output is unchanged."""
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise ValueError(f"completed {description} exists with different content")
        return
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def read_csv(path: Path, required: Iterable[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    missing = set(required) - set(rows[0])
    if missing:
        raise ValueError(f"{path} missing fields: {sorted(missing)}")
    return rows


def safe_path(path: Path) -> Path:
    candidate = path.resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ValueError(f"path outside QCT: {path}")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def read_profiles(path: Path) -> list[dict[str, str]]:
    rows = read_csv(path, {"unit_id", "cohort", "structure_cluster_id", "path", "workbook_sha256"})
    output: list[dict[str, str]] = []
    seen_units: set[str] = set()
    seen_hashes: set[str] = set()
    for row in rows:
        unit = row["unit_id"]
        if not unit or unit in seen_units:
            raise ValueError(f"duplicate profile unit: {unit!r}")
        seen_units.add(unit)
        path_value = safe_path(ROOT / row["path"])
        actual = sha256(path_value)
        if actual != row["workbook_sha256"].lower():
            raise ValueError(f"profile hash mismatch: {row['path']}")
        if actual in seen_hashes:
            raise ValueError(f"duplicate observed workbook hash: {actual}")
        seen_hashes.add(actual)
        output.append({
            "unit_id": unit,
            "cohort": row["cohort"],
            "structure_cluster_id": row["structure_cluster_id"],
            "path": row["path"],
            "workbook_sha256": actual,
        })
    return sorted(output, key=lambda item: item["unit_id"])


def parse_cells(value: str) -> list[str]:
    output: list[str] = []
    for raw in (value or "").replace("|", ";").split(";"):
        cell = raw.strip()
        if cell and cell not in output:
            if "!" not in cell or not cell.rsplit("!", 1)[1]:
                raise ValueError(f"invalid cell label: {cell!r}")
            output.append(cell)
    return output


def load_gate2_events(gate2_dir: Path, profiles: list[dict[str, str]]) -> list[dict[str, object]]:
    receipt_path = safe_path(gate2_dir / "gate2_receipt.json")
    events_path = safe_path(gate2_dir / "event_scores.jsonl")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("protocol") != "formulaguard_model_discovery_gate2_score_v1":
        raise ValueError("Gate 2 receipt protocol mismatch")
    if receipt.get("branch_decision", {}).get("selected_branch") != "C":
        raise ValueError("branch C is not authorized by the Gate 2 receipt")
    if receipt.get("event_scores_sha256") != sha256(events_path):
        raise ValueError("Gate 2 event score hash mismatch")
    recorded = dict(receipt)
    receipt_hash = recorded.pop("receipt_sha256", None)
    if receipt_hash != stable_hash(recorded):
        raise ValueError("Gate 2 receipt hash mismatch")
    expected_hashes = {row["workbook_sha256"] for row in profiles}
    rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    with events_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            event_id = str(row.get("event_id", ""))
            digest = str(row.get("workbook_sha256", ""))
            if not event_id or event_id in seen_ids:
                raise ValueError(f"duplicate or empty Gate 2 event id: {event_id!r}")
            if digest not in expected_hashes:
                raise ValueError(f"Gate 2 event references unknown workbook: {digest}")
            seen_ids.add(event_id)
            row["source_formula_cells"] = parse_cells(";".join(row.get("source_formula_cells", [])))
            rows.append(row)
    if len(rows) != 220:
        raise ValueError(f"unexpected Gate 2 event count: {len(rows)}")
    return rows


def load_public_history() -> dict[str, Path]:
    """Map an observed public-pressure workbook hash to its original version."""

    result: dict[str, Path] = {}
    for row in read_csv(DEFAULT_PUBLIC_MANIFEST, {"workbook", "original_workbook", "case_kind", "include"}):
        if row.get("include") != "1":
            continue
        current_rel = row["workbook"] if row["case_kind"] == "error" else row["original_workbook"]
        current = safe_path(ROOT / "results/v5_psl_pressure_inputs" / current_rel)
        original = safe_path(ROOT / "results/v5_psl_pressure_inputs" / row["original_workbook"])
        result[sha256(current)] = original
    return result


def canonical_formula(formula: str) -> str:
    return "".join(str(formula).upper().split())


def parse_label(cell: str) -> tuple[str, str]:
    sheet, address = cell.rsplit("!", 1)
    parse_address(address)
    return sheet, address


def formula_label(key: tuple[str, str]) -> str:
    return f"{key[0]}!{key[1]}"


def graph_distance_rank(model: WorkbookModel, output: tuple[str, str], fallback: Mapping[str, int]) -> tuple[list[str], dict[str, object]]:
    graph = model.dependency_graph()
    formulas = set(model.formula_cells)
    cone = (set(graph.ancestors(output)) | {output}) & formulas
    distances: dict[tuple[str, str], int] = {}
    for cell in cone:
        distance = graph.shortest_path_length(cell, output)
        distances[cell] = int(distance) if distance is not None else 10**9
    ranked = sorted(
        cone,
        key=lambda cell: (-distances[cell], fallback.get(formula_label(cell), 10**9), cell[0], parse_address(cell[1]).row, parse_address(cell[1]).col),
    )
    return [formula_label(cell) for cell in ranked], {
        "output_cell": formula_label(output),
        "cone_formula_count": len(cone),
        "output_distance_max": max(distances.values()) if distances else None,
    }


def choose_visible_output(model: WorkbookModel) -> tuple[tuple[str, str] | None, dict[str, object]]:
    graph = model.dependency_graph()
    sinks = graph.sinks(model.formula_cells)
    if not sinks:
        return None, {"reason": "no_formula_sink"}
    choices = []
    for sink in sinks:
        cone = (set(graph.ancestors(sink)) | {sink}) & set(model.formula_cells)
        choices.append((len(cone), sink[0], parse_address(sink[1]).row, parse_address(sink[1]).col, sink))
    choices.sort(key=lambda value: (-value[0], value[1], value[2], value[3]))
    chosen = choices[0][-1]
    return chosen, {"selection_rule": "visible_formula_sink_with_largest_ancestor_cone", "candidate_sink_count": len(sinks)}


def history_changes(model: WorkbookModel, reference: Path | None) -> tuple[list[str], dict[str, object]]:
    if reference is None:
        return [], {"available": False, "reason": "no_verified_previous_workbook"}
    previous = WorkbookModel.from_xlsx(reference)
    keys = sorted(set(model.formulas) | set(previous.formulas))
    changed = [
        formula_label(key)
        for key in keys
        if canonical_formula(model.formulas.get(key, "")) != canonical_formula(previous.formulas.get(key, ""))
        and key in model.formulas
    ]
    return changed, {
        "available": True,
        "reference_sha256": sha256(reference),
        "changed_formula_count": len(changed),
    }


def exact_constraint_action(changed: Sequence[str], model: WorkbookModel, reference: Path | None) -> tuple[list[str], dict[str, object]]:
    if reference is None:
        return [], {"available": False, "reason": "no_verified_previous_workbook"}
    if not changed:
        return [], {"available": True, "violated": False, "reason": "no_formula_constraint_violation"}
    # One exact cell/formula constraint is deliberately limited to one action.
    target = min(changed, key=lambda value: (value.split("!", 1)[0], parse_address(value.rsplit("!", 1)[1]).row, parse_address(value.rsplit("!", 1)[1]).col))
    return [target], {
        "available": True,
        "violated": True,
        "constraint_count": 1,
        "constraint_target": target,
        "reference_sha256": sha256(reference),
    }


def metric(action: Sequence[str], sources: Sequence[str]) -> dict[str, object]:
    source = set(sources)
    actions = list(dict.fromkeys(action))
    hit = bool(set(actions) & source)
    return {"acted": int(bool(actions)), "hit": int(hit), "action_count": len(actions), "rank": (next((i + 1 for i, cell in enumerate(actions) if cell in source), None))}


def structure_macro(rows: Sequence[Mapping[str, object]], condition: str, case_kind: str) -> dict[str, object]:
    selected = [row for row in rows if row["case_kind"] == case_kind and row["conditions"][condition]["available"]]
    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in selected:
        groups[str(row["structure_group"])].append(row)
    values: list[float] = []
    for group in groups.values():
        values.append(statistics.fmean(float(row["conditions"][condition]["metric"]["hit"]) for row in group))
    return {"events": len(selected), "groups": len(groups), "hit_rate": statistics.fmean(values) if values else None}


def summarize(rows: Sequence[Mapping[str, object]], condition: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for kind in ("error", "control"):
        selected = [row for row in rows if row["case_kind"] == kind and row["conditions"][condition]["available"]]
        details = [row["conditions"][condition]["metric"] for row in selected]
        acted = sum(int(item["acted"]) for item in details)
        hits = sum(int(item["hit"]) for item in details)
        source_events = sum(bool(row["source_formula_cells"]) for row in selected)
        result[kind] = {
            "events": len(selected),
            "acted_events": acted,
            "action_rate": acted / len(selected) if selected else None,
            "acted_hits": hits,
            "acted_precision": hits / acted if acted else None,
            "source_action_coverage": hits / source_events if source_events and kind == "error" else None,
            "structure_macro": structure_macro(rows, condition, kind),
        }
    return result


def score(*, profiles_path: Path, gate2_dir: Path, output_dir: Path) -> Path:
    profiles_path = profiles_path.resolve()
    profiles = read_profiles(profiles_path)
    profile_by_hash = {row["workbook_sha256"]: row for row in profiles}
    events = load_gate2_events(gate2_dir.resolve(), profiles)
    history_by_hash = load_public_history()
    workbook_cache: dict[str, tuple[WorkbookModel, dict[str, int], dict[str, object]]] = {}
    rows: list[dict[str, object]] = []
    for event in events:
        digest = str(event["workbook_sha256"])
        profile = profile_by_hash[digest]
        if digest not in workbook_cache:
            model = WorkbookModel.from_xlsx(ROOT / profile["path"])
            v4_rank = {cell: index for index, cell in enumerate(event.get("v4_rank", []), 1)}
            output, output_meta = choose_visible_output(model)
            workbook_cache[digest] = (model, v4_rank, {"output": output, **output_meta})
        model, fallback, output_meta = workbook_cache[digest]
        reference = history_by_hash.get(digest)
        changed, history_meta = history_changes(model, reference)
        actions: dict[str, list[str]] = {}
        condition_meta: dict[str, dict[str, object]] = {}
        history_available = bool(history_meta.get("available"))
        actions["history_version"] = changed
        condition_meta["history_version"] = {**history_meta, "burden": "full_previous_xlsx", "metric": metric(changed, event["source_formula_cells"])}
        output = output_meta.get("output")
        if output is None:
            output_rank: list[str] = []
            output_info = {"available": False, "reason": output_meta.get("reason", "no_output")}
        else:
            output_rank, rank_info = graph_distance_rank(model, output, fallback)
            output_info = {"available": True, **rank_info}
        actions["key_output"] = output_rank[:REVIEW_BUDGET]
        condition_meta["key_output"] = {**output_info, "burden": "one_output_cell", "metric": metric(actions["key_output"], event["source_formula_cells"])}
        fail_marker = event["case_kind"] == "error"
        actions["pass_fail"] = actions["key_output"] if fail_marker else []
        condition_meta["pass_fail"] = {**output_info, "available": bool(output_info.get("available")), "marker": "fail" if fail_marker else "pass", "burden": "one_output_cell_plus_one_bit", "metric": metric(actions["pass_fail"], event["source_formula_cells"])}
        constraint_action, constraint_meta = exact_constraint_action(changed, model, reference)
        actions["domain_constraint"] = constraint_action
        condition_meta["domain_constraint"] = {**constraint_meta, "burden": "one_cell_formula_constraint", "metric": metric(constraint_action, event["source_formula_cells"])}
        rows.append({
            "event_id": event["event_id"], "cohort": event["cohort"], "case_kind": event["case_kind"],
            "unit_id": event["unit_id"], "workbook_sha256": digest, "structure_group": event["structure_group"],
            "source_formula_cells": event["source_formula_cells"], "output_selection": output_meta,
            "history_available": history_available, "actions": actions, "conditions": condition_meta,
        })

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / "event_scores.jsonl"
    event_bytes = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in sorted(rows, key=lambda item: str(item["event_id"]))
    ).encode("utf-8")
    write_immutable(events_path, event_bytes, description="Branch C event scores")
    summaries = {condition: summarize(rows, condition) for condition in CONDITIONS}
    payload: dict[str, object] = {
        "protocol": PROTOCOL, "complete": True, "scorer_version": "branch-c-min-info-v1",
        "git_commit": git_commit(), "profiles": {"path": str(profiles_path.relative_to(ROOT)), "sha256": sha256(profiles_path), "count": len(profiles)},
        "gate2": {"path": str(gate2_dir.resolve().relative_to(ROOT)), "receipt_sha256": sha256(gate2_dir / "gate2_receipt.json"), "event_scores_sha256": sha256(gate2_dir / "event_scores.jsonl")},
        "fixed_conditions": {
            "history_version": "exact formula diffs against a verified previous public-pressure workbook when available",
            "key_output": "one visible formula sink with the largest ancestor cone; ancestors ranked farthest-first then frozen V4 order",
            "pass_fail": "same key-output cone; act only for simulated fail marker (error events), abstain for pass marker (controls)",
            "domain_constraint": "one exact formula equality constraint at the first changed cell; reference-backed upper-bound simulation",
            "review_budget": REVIEW_BUDGET,
        },
        "event_count": len(rows), "available_event_counts": {condition: sum(row["conditions"][condition]["available"] for row in rows) for condition in CONDITIONS},
        "summaries": summaries,
        "limitations": [
            "key_output uses a deterministic offline proxy for a user-selected important output; it is not a no-label model result",
            "pass_fail marker uses revealed case kind to simulate one user bit",
            "history_version and domain_constraint are evaluated only where a verified public paired workbook exists",
            "domain_constraint is an exact reference-backed upper bound and is not a novel formula-localization algorithm",
        ],
        "event_scores_sha256": sha256(events_path),
    }
    payload["receipt_sha256"] = stable_hash(payload)
    receipt_path = output_dir / "branch_c_receipt.json"
    if receipt_path.exists():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError("branch C output exists with different content")
    else:
        temporary = receipt_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, receipt_path)
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--gate2", type=Path, default=DEFAULT_GATE2)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        print(score(profiles_path=args.profiles, gate2_dir=args.gate2, output_dir=args.output))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"model-discovery branch C refused: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
