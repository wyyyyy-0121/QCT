"""Score the frozen, label-free model-discovery shards once at Gate 2.

The command has a deliberately hard boundary between prediction and scoring:
it first verifies the signal and V4 baseline completion receipts, including
every shard hash and the absence of label inputs.  Only after that validation
does it read the revealed development manifests.  The output is a receipt,
event table, structure-group summaries, and deterministic Gate 2 decisions.

This is a scoring/audit command, not a parameter tuner.  The four atomic
signal channels, five-cell budget, selector tie order, action definition, and
permutation seed are fixed constants below.  A completed output is immutable.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.model_discovery import validate_label_free_output

SCORER_PROTOCOL = "formulaguard_model_discovery_gate2_score_v1"
SIGNAL_RUN_PROTOCOL = "formulaguard_model_discovery_signal_run_v1"
V4_RUN_PROTOCOL = "formulaguard_model_discovery_v4_baseline_run_v1"
CHANNELS = ("combined", "peer", "role", "impact")
SELECTOR_TIE_ORDER = CHANNELS
REVIEW_BUDGET = 5
PERMUTATION_SEED = 20260831
PERMUTATION_ROUNDS = 1000

DEFAULT_PROFILES = ROOT / "results/core_reset_b_phase0/observation_profiles.csv"
DEFAULT_SIGNAL_RUN = ROOT / "results/model_discovery_signal_audit_observed"
DEFAULT_V4_RUN = ROOT / "results/model_discovery_v4_baseline"
DEFAULT_OUTPUT = ROOT / "results/model_discovery_gate2"
GROUPS = ROOT / "results/core_reset_b_phase0/scoring_groups.csv"
ENRON_MANIFEST = ROOT / "data/external/enron/manifest.csv"
PUBLIC_MANIFEST = ROOT / "results/v5_psl_pressure_inputs/public_pressure_manifest.csv"
HIST_MANIFEST = ROOT / "data/v4_v52_blind/public/manifest.csv"
HIST_LABELS = ROOT / "results/v4_v52_independent_100_scored/independent_scored_events.csv"

FORBIDDEN_LABEL_PREFIXES = (
    "data/external/v5_psl/revealed_trial",
    "data/external/v5_psl/custodian",
    "data/external/v5_psl/final_blind",
)
FORBIDDEN_PREDICTION_KEYS = {
    "correct_formula", "source_cell", "source_cells", "error_type", "case_kind",
    "corpus_id", "template_id", "filename_semantics", "secret_labels", "expected_output",
    "pass_fail",
}


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


def combined_hash(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


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


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def safe_qct_file(path: Path) -> Path:
    candidate = path.resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ValueError(f"file outside QCT allowlist: {path}")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    relative = candidate.relative_to(ROOT).as_posix()
    if any(relative == prefix or relative.startswith(prefix + "/") for prefix in FORBIDDEN_LABEL_PREFIXES):
        raise ValueError(f"protected file may not be read by Gate 2: {relative}")
    return candidate


def read_profiles(path: Path) -> list[dict[str, str]]:
    rows = read_csv(path, {"unit_id", "cohort", "structure_cluster_id", "path", "workbook_sha256"})
    seen_units: set[str] = set()
    seen_paths: set[str] = set()
    output: list[dict[str, str]] = []
    for row in rows:
        unit = str(row["unit_id"])
        if not unit or unit in seen_units:
            raise ValueError(f"duplicate profile unit: {unit!r}")
        seen_units.add(unit)
        workbook = safe_qct_file(ROOT / row["path"])
        if workbook.as_posix() in seen_paths:
            raise ValueError(f"duplicate profile path: {workbook}")
        seen_paths.add(workbook.as_posix())
        actual = sha256(workbook)
        declared = str(row["workbook_sha256"]).lower()
        if actual != declared:
            raise ValueError(f"profile hash mismatch for {row['path']}")
        output.append({
            "unit_id": unit,
            "cohort": str(row["cohort"]),
            "structure_cluster_id": str(row["structure_cluster_id"]),
            "path": str(row["path"]),
            "workbook_sha256": actual,
        })
    return sorted(output, key=lambda row: row["unit_id"])


def shard_name(unit_id: str) -> str:
    return hashlib.sha256(unit_id.encode("utf-8")).hexdigest() + ".json"


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    return value


def _validate_signal_run(
    run_dir: Path, profiles: list[dict[str, str]], profiles_hash: str
) -> dict[str, object]:
    metadata = _load_json(safe_qct_file(run_dir / "metadata.json"))
    complete = _load_json(safe_qct_file(run_dir / "complete.json"))
    if metadata.get("protocol") != SIGNAL_RUN_PROTOCOL:
        raise ValueError("signal metadata protocol mismatch")
    if complete.get("protocol") != SIGNAL_RUN_PROTOCOL or complete.get("complete") is not True:
        raise ValueError("signal completion receipt is not complete")
    if complete.get("profiles_sha256") != profiles_hash or metadata.get("profiles_sha256") != profiles_hash:
        raise ValueError("signal profiles hash does not match scoring profiles")
    if complete.get("label_inputs_to_prediction") != [] or metadata.get("label_inputs_to_prediction") != []:
        raise ValueError("signal run reports label inputs")
    if complete.get("forbidden_label_fields") != metadata.get("forbidden_label_fields"):
        raise ValueError("signal forbidden-field receipt mismatch")
    shards_dir = run_dir / "shards"
    paths = sorted(shards_dir.glob("*.json"), key=lambda path: path.name)
    if len(paths) != len(profiles) or complete.get("shard_count") != len(profiles):
        raise ValueError(f"signal shard count mismatch: {len(paths)} != {len(profiles)}")
    expected = {row["unit_id"]: row for row in profiles}
    seen: set[str] = set()
    for path in paths:
        record = _load_json(safe_qct_file(path))
        if record.get("protocol") != SIGNAL_RUN_PROTOCOL:
            raise ValueError(f"signal shard protocol mismatch: {path.name}")
        unit = str(record.get("unit_id", ""))
        if unit in seen or unit not in expected or path.name != shard_name(unit):
            raise ValueError(f"signal shard identity mismatch: {path.name}")
        seen.add(unit)
        if record.get("workbook_sha256") != expected[unit]["workbook_sha256"]:
            raise ValueError(f"signal workbook hash mismatch: {path.name}")
        audit = record.get("audit")
        if not isinstance(audit, dict):
            raise ValueError(f"signal audit missing: {path.name}")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
        errors = validate_label_free_output(audit)
        if errors:
            raise ValueError(f"signal validation failed {path.name}: {'; '.join(errors)}")
        if audit.get("input_sha256") != expected[unit]["workbook_sha256"]:
            raise ValueError(f"signal input hash mismatch: {path.name}")
        if audit.get("label_inputs") != []:
            raise ValueError(f"signal shard has labels: {path.name}")
    if complete.get("combined_shards_sha256") != combined_hash(paths):
        raise ValueError("signal combined shard hash mismatch")
    return {"metadata": metadata, "complete": complete, "paths": paths}


def _validate_v4_run(
    run_dir: Path, profiles: list[dict[str, str]], profiles_hash: str
) -> dict[str, object]:
    metadata = _load_json(safe_qct_file(run_dir / "metadata.json"))
    complete = _load_json(safe_qct_file(run_dir / "complete.json"))
    if metadata.get("protocol") != V4_RUN_PROTOCOL:
        raise ValueError("V4 metadata protocol mismatch")
    if complete.get("protocol") != V4_RUN_PROTOCOL or complete.get("complete") is not True:
        raise ValueError("V4 completion receipt is not complete")
    if complete.get("profiles_sha256") != profiles_hash or metadata.get("profiles_sha256") != profiles_hash:
        raise ValueError("V4 profiles hash does not match scoring profiles")
    if complete.get("label_inputs_to_prediction") != [] or metadata.get("label_inputs_to_prediction") != []:
        raise ValueError("V4 run reports label inputs")
    paths = sorted((run_dir / "shards").glob("*.json"), key=lambda path: path.name)
    if len(paths) != len(profiles) or complete.get("shard_count") != len(profiles):
        raise ValueError(f"V4 shard count mismatch: {len(paths)} != {len(profiles)}")
    expected = {row["unit_id"]: row for row in profiles}
    seen: set[str] = set()
    for path in paths:
        record = _load_json(safe_qct_file(path))
        if record.get("protocol") != V4_RUN_PROTOCOL:
            raise ValueError(f"V4 shard protocol mismatch: {path.name}")
        unit = str(record.get("unit_id", ""))
        if unit in seen or unit not in expected or path.name != shard_name(unit):
            raise ValueError(f"V4 shard identity mismatch: {path.name}")
        seen.add(unit)
        if record.get("workbook_sha256") != expected[unit]["workbook_sha256"]:
            raise ValueError(f"V4 workbook hash mismatch: {path.name}")
        if record.get("label_inputs") != []:
            raise ValueError(f"V4 shard has labels: {path.name}")
        ranking = record.get("ranking")
        if not isinstance(ranking, list) or len(ranking) != int(record.get("formula_count", -1)):
            raise ValueError(f"V4 ranking malformed: {path.name}")
        cells = [str(item.get("cell", "")) for item in ranking if isinstance(item, dict)]
        if len(cells) != len(set(cells)) or any("!" not in cell for cell in cells):
            raise ValueError(f"V4 ranking cells malformed: {path.name}")
        unhashed = dict(record)
        recorded = unhashed.pop("audit_sha256", None)
        if recorded != stable_hash(unhashed):
            raise ValueError(f"V4 audit hash mismatch: {path.name}")
    if complete.get("combined_shards_sha256") != combined_hash(paths):
        raise ValueError("V4 combined shard hash mismatch")
    return {"metadata": metadata, "complete": complete, "paths": paths}


def parse_cells(value: str) -> list[str]:
    cells: list[str] = []
    for raw in (value or "").replace("|", ";").split(";"):
        cell = raw.strip()
        if cell and cell not in cells:
            if "!" not in cell or not cell.rsplit("!", 1)[1]:
                raise ValueError(f"invalid cell label: {cell!r}")
            cells.append(cell)
    return cells


def _event(
    *, event_id: str, cohort: str, case_kind: str, path: Path, source_cells: list[str],
    label_file: Path, label_row: int, extra: Mapping[str, str] | None = None,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "cohort": cohort,
        "case_kind": case_kind,
        "path": safe_qct_file(path),
        "source_cells": source_cells,
        "label_file": _relative(label_file),
        "label_row": label_row,
        "extra": dict(extra or {}),
    }


def load_revealed_events() -> tuple[list[dict[str, object]], list[str]]:
    """Read only the three revealed development sources after shard locking."""

    events: list[dict[str, object]] = []
    files = [ENRON_MANIFEST, PUBLIC_MANIFEST, HIST_MANIFEST, HIST_LABELS]

    for index, row in enumerate(read_csv(ENRON_MANIFEST, {"instance_id", "workbook", "include", "source_cells", "source_cell"}), 2):
        if row.get("include") != "1":
            continue
        source = parse_cells(row.get("source_cells") or row.get("source_cell", ""))
        events.append(_event(
            event_id=row["instance_id"], cohort="enron", case_kind="error",
            path=ROOT / "data/external/enron" / row["workbook"], source_cells=source,
            label_file=ENRON_MANIFEST, label_row=index,
            extra={"error_type": row.get("error_type", ""), "error_subtype": row.get("error_subtype", "")},
        ))

    for index, row in enumerate(read_csv(PUBLIC_MANIFEST, {"instance_id", "corpus_id", "workbook", "original_workbook", "case_kind", "source_cells", "include"}), 2):
        if row.get("include") != "1":
            continue
        case_kind = row["case_kind"]
        relative = row["workbook"] if case_kind == "error" else row["original_workbook"]
        events.append(_event(
            event_id=row["instance_id"], cohort="public:" + row["corpus_id"], case_kind=case_kind,
            path=ROOT / "results/v5_psl_pressure_inputs" / relative,
            source_cells=parse_cells(row.get("source_cells", "")), label_file=PUBLIC_MANIFEST, label_row=index,
            extra={"identifiability": row.get("identifiability", ""), "control_subtype": row.get("control_subtype", "")},
        ))

    hist_manifest = {
        row["instance_id"]: row
        for row in read_csv(HIST_MANIFEST, {"instance_id", "workbook"})
    }
    hist_rows = read_csv(HIST_LABELS, {"instance_id", "source_cells"})
    for index, row in enumerate(hist_rows, 2):
        if row["instance_id"] not in hist_manifest:
            raise ValueError(f"historical label has no public workbook: {row['instance_id']}")
        events.append(_event(
            event_id=row["instance_id"], cohort="historical_100", case_kind="error",
            path=ROOT / "data/v4_v52_blind/public" / hist_manifest[row["instance_id"]]["workbook"],
            source_cells=parse_cells(row.get("source_cells", "")), label_file=HIST_LABELS, label_row=index,
            extra={"evidence_cohort": row.get("evidence_cohort", "")},
        ))

    event_ids = [str(event["event_id"]) for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("revealed event IDs must be unique across label manifests")
    if len(events) != 30 + 90 + 100:
        raise ValueError(f"unexpected revealed event count: {len(events)}")
    return events, [_relative(safe_qct_file(path)) for path in files]


def _load_shards(signal_dir: Path, v4_dir: Path, profiles: list[dict[str, str]]) -> dict[str, dict[str, object]]:
    by_unit: dict[str, dict[str, object]] = {}
    for profile in profiles:
        unit = profile["unit_id"]
        name = shard_name(unit)
        signal = _load_json(safe_qct_file(signal_dir / "shards" / name))
        baseline = _load_json(safe_qct_file(v4_dir / "shards" / name))
        by_unit[unit] = {
            "profile": profile,
            "signal": signal["audit"],
            "v4": baseline["ranking"],
        }
    return by_unit


def _rank_cells(ranking: object) -> list[str]:
    if not isinstance(ranking, list):
        raise ValueError("ranking must be a list")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    if ranking and isinstance(ranking[0], dict):
        return [str(item["cell"]) for item in ranking]
    return [str(cell) for cell in ranking]


def _min_rank(rank: Mapping[str, int], sources: Sequence[str]) -> int | None:
    values = [rank[cell] for cell in sources if cell in rank]
    return min(values) if values else None


def _metric(rank_cells: Sequence[str], sources: Sequence[str]) -> dict[str, object]:
    positions = {cell: index for index, cell in enumerate(rank_cells, 1)}
    rank = _min_rank(positions, sources)
    return {
        "rank": rank,
        "source_found": int(rank is not None),
        "top1": int(rank is not None and rank <= 1),
        "top5": int(rank is not None and rank <= REVIEW_BUDGET),
        "mrr": 1.0 / rank if rank is not None else 0.0,
    }


def _structure_macro(rows: Sequence[Mapping[str, object]], method: str, case_kind: str | None = "error") -> dict[str, object]:
    selected = [row for row in rows if case_kind is None or row["case_kind"] == case_kind]
    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in selected:
        groups[str(row["structure_group"])].append(row)
    metrics: dict[str, float | None] = {}
    for key in ("top1", "top5", "mrr", "region_hit", "source_block_coverage"):
        values: list[float] = []
        for group_rows in groups.values():
            group_values = [row["metrics"][method][key] for row in group_rows]
            observed = [float(value) for value in group_values if value is not None]
            if observed:
                values.append(statistics.fmean(observed))
        metrics[key] = statistics.fmean(values) if values else None
    return {"groups": len(groups), "events": len(selected), **metrics}


def _record_action_cells(audit: Mapping[str, object], channel: str) -> tuple[list[str], list[str]]:
    records = audit.get("records")
    if not isinstance(records, list):
        raise ValueError("signal records missing")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    by_cell = {str(row["cell"]): row for row in records if isinstance(row, dict) and "cell" in row}
    review = audit.get("review_cells", {}).get(channel) if isinstance(audit.get("review_cells"), dict) else None
    if not isinstance(review, list):
        raise ValueError(f"review cells missing for {channel}")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    review_cells: list[str] = []
    action_cells: list[str] = []
    seen_regions: set[str] = set()
    for raw in review[:REVIEW_BUDGET]:
        cell = str(raw)
        if cell not in by_cell or cell in review_cells:
            continue
        review_cells.append(cell)
        row = by_cell[cell]
        # A selective action requires defect evidence.  Ambiguous, unsupported,
        # and impact-only records remain visible in the review list but do not
        # trigger an error action.
        if row.get("status") != "evidence_supported":
            continue
        region = str(row.get("region_id", ""))
        if region and region in seen_regions:
            continue
        if region:
            seen_regions.add(region)
        action_cells.append(cell)
    return review_cells, action_cells


def _region_sets(audit: Mapping[str, object], sources: Sequence[str]) -> tuple[set[str], dict[str, str]]:
    records = audit.get("records")
    if not isinstance(records, list):
        raise ValueError("signal records missing")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    by_cell = {str(row["cell"]): row for row in records if isinstance(row, dict) and "cell" in row}
    regions = {str(by_cell[cell].get("region_id", "")) for cell in sources if cell in by_cell}
    regions.discard("")
    return regions, {cell: str(by_cell[cell].get("region_id", "")) for cell in by_cell}


def _oracle_rank(audit: Mapping[str, object], sources: Sequence[str], *, selector: bool) -> tuple[list[str], str | None]:
    rankings = audit.get("rankings")
    if not isinstance(rankings, dict):
        raise ValueError("signal rankings missing")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    channel_ranks = {channel: _rank_cells(rankings[channel]) for channel in CHANNELS}
    if selector:
        choices = []
        for channel in CHANNELS:
            metric = _metric(channel_ranks[channel], sources)
            choices.append((metric["rank"] if metric["rank"] is not None else math.inf, CHANNELS.index(channel), channel))
        choices.sort()
        channel = choices[0][2]
        return channel_ranks[channel], channel
    result: list[str] = []
    for channel in CHANNELS:
        for cell in channel_ranks[channel][:REVIEW_BUDGET]:
            if cell not in result:
                result.append(cell)
    return result, None


def attach_events(events: list[dict[str, object]], profiles: list[dict[str, str]], shards: Mapping[str, Mapping[str, object]]) -> list[dict[str, object]]:
    by_hash = {row["workbook_sha256"]: row for row in profiles}
    output: list[dict[str, object]] = []
    for event in events:
        path = safe_qct_file(event["path"])
        digest = sha256(path)
        if digest not in by_hash:
            raise ValueError(f"revealed label workbook is not in observation profiles: {path}")
        profile = by_hash[digest]
        unit = profile["unit_id"]
        payload = shards[unit]
        audit = payload["signal"]
        records = audit.get("records")
        if not isinstance(records, list):
            raise ValueError(f"missing records for {unit}")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
        formula_cells = {str(row["cell"]) for row in records if isinstance(row, dict) and "cell" in row}
        source_all = list(event["source_cells"])
        source_formula = [cell for cell in source_all if cell in formula_cells]
        non_formula = [cell for cell in source_all if cell not in formula_cells]
        if event["case_kind"] == "error" and not source_all:
            raise ValueError(f"error event has no source cells: {event['event_id']}")
        region_sources, regions_by_cell = _region_sets(audit, source_formula)
        row: dict[str, object] = {
            "event_id": event["event_id"],
            "cohort": event["cohort"],
            "case_kind": event["case_kind"],
            "unit_id": unit,
            "workbook_sha256": digest,
            "workbook_group": "workbook:" + digest,
            "structure_group": profile["structure_cluster_id"],
            "source_cells": source_all,
            "source_formula_cells": source_formula,
            "non_formula_source_cells": non_formula,
            "source_region_ids": sorted(region_sources),
            "audit": audit,
            "v4_rank": _rank_cells(payload["v4"]),
            "label_file": event["label_file"],
            "label_row": event["label_row"],
        }
        metrics: dict[str, dict[str, object]] = {}
        review_cells: dict[str, list[str]] = {}
        action_cells: dict[str, list[str]] = {}
        for channel in CHANNELS:
            rank = _rank_cells(audit["rankings"][channel])
            regions = {regions_by_cell[cell] for cell in rank[:REVIEW_BUDGET] if regions_by_cell.get(cell)}
            m = _metric(rank, source_formula)
            m["region_hit"] = int(bool(regions & region_sources)) if region_sources else 0
            m["source_block_coverage"] = int(m["top5"])
            metrics[channel] = m
            review, action = _record_action_cells(audit, channel)
            review_cells[channel] = review
            action_cells[channel] = action
        metrics["v4"] = _metric(row["v4_rank"], source_formula)
        metrics["v4"]["region_hit"] = None
        metrics["v4"]["source_block_coverage"] = int(metrics["v4"]["top5"])
        for name, selector in (("oracle_union", False), ("oracle_selector", True)):
            rank, channel = _oracle_rank(audit, source_formula, selector=selector)
            m = _metric(rank, source_formula)
            prefix = rank[:REVIEW_BUDGET] if selector else rank
            regions = {regions_by_cell[cell] for cell in prefix if regions_by_cell.get(cell)}
            m["region_hit"] = int(bool(regions & region_sources)) if region_sources else 0
            m["source_block_coverage"] = int(m["top5"]) if selector else int(m["source_found"])
            if not selector:
                # The union is an information upper bound, not a five-cell
                # action.  Keep its full review cost and do not call it Top-5.
                m["top5"] = None
                m["union_review_cells"] = len(rank)
            metrics[name] = m
            if channel:
                row[name + "_channel"] = channel
        row["metrics"] = metrics
        row["review_cells"] = review_cells
        row["action_cells"] = action_cells
        output.append(row)
    return output


def _event_action(row: Mapping[str, object], method: str) -> dict[str, object]:
    sources = set(row["source_formula_cells"])
    cells = set(row["action_cells"].get(method, []))
    acted = int(bool(cells))
    hit = int(bool(cells & sources))
    return {"acted": acted, "hit": hit, "action_cell_count": len(cells)}


def action_summary(rows: Sequence[Mapping[str, object]], method: str, case_kind: str | None = None) -> dict[str, object]:
    selected = [row for row in rows if case_kind is None or row["case_kind"] == case_kind]
    actions = [_event_action(row, method) for row in selected]
    acted = sum(int(item["acted"]) for item in actions)
    hits = sum(int(item["hit"]) for item in actions)
    source_events = sum(bool(row["source_formula_cells"]) for row in selected)
    return {
        "events": len(selected),
        "acted_events": acted,
        "action_rate": acted / len(selected) if selected else None,
        "acted_hits": hits,
        "acted_precision": hits / acted if acted else None,
        "source_events": source_events,
        "error_source_action_coverage": hits / source_events if source_events else None,
        "inspected_cells": sum(int(item["action_cell_count"]) for item in actions),
    }


def _choose_channel(training: Sequence[Mapping[str, object]]) -> str:
    # Fixed, auditable outer selector: maximize structure-group macro Top-5;
    # then MRR; ties follow the pre-registered channel order.
    scores: list[tuple[float, float, int, str]] = []
    for channel in CHANNELS:
        macro = _structure_macro(training, channel, "error")
        scores.append((float(macro["top5"] or 0.0), float(macro["mrr"] or 0.0), -CHANNELS.index(channel), channel))
    scores.sort(reverse=True)
    return scores[0][3]


def fixed_selector_rows(rows: Sequence[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, str]]:
    groups = sorted({str(row["structure_group"]) for row in rows})
    selected_channel: dict[str, str] = {}
    output: list[dict[str, object]] = []
    for group in groups:
        training = [row for row in rows if str(row["structure_group"]) != group and row["case_kind"] == "error"]
        selected_channel[group] = _choose_channel(training) if training else CHANNELS[0]
        for row in rows:
            if str(row["structure_group"]) != group:
                continue
            channel = selected_channel[group]
            clone = dict(row)
            clone["selector_channel"] = channel
            clone["selector_method"] = "fixed_selector@5"
            clone["selector_metrics"] = row["metrics"][channel]
            clone["selector_action"] = _event_action(row, channel)
            output.append(clone)
    return output, selected_channel


def _fixed_macro(rows: Sequence[Mapping[str, object]], case_kind: str = "error") -> dict[str, object]:
    selected = [row for row in rows if row["case_kind"] == case_kind]
    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in selected:
        groups[str(row["structure_group"])].append(row)
    metrics: dict[str, float | None] = {}
    for key in ("top1", "top5", "mrr", "region_hit", "source_block_coverage"):
        group_values: list[float] = []
        for group_rows in groups.values():
            values = [row["selector_metrics"][key] for row in group_rows]
            observed = [float(value) for value in values if value is not None]
            if observed:
                group_values.append(statistics.fmean(observed))
        metrics[key] = statistics.fmean(group_values) if group_values else None
    return {"groups": len(groups), "events": len(selected), **metrics}


def leave_one_cohort_out(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    """Evaluate a channel selected without seeing the held-out cohort."""

    output: dict[str, object] = {}
    cohorts = sorted({str(row["cohort"]) for row in rows})
    for cohort in cohorts:
        training = [row for row in rows if row["cohort"] != cohort and row["case_kind"] == "error"]
        testing = [row for row in rows if row["cohort"] == cohort and row["case_kind"] == "error"]
        channel = _choose_channel(training) if training else CHANNELS[0]
        output[cohort] = {
            "selected_channel": channel,
            "error": _structure_macro(testing, channel, "error") if testing else None,
            "events": len(testing),
        }
    return output


def _paired_diff(rows: Sequence[Mapping[str, object]], method: str, baseline: str, cohort: str) -> dict[str, object]:
    selected = [row for row in rows if row["cohort"] == cohort and row["case_kind"] == "error"]
    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in selected:
        groups[str(row["structure_group"])].append(row)
    diffs = []
    gain_events: set[str] = set()
    loss_events: set[str] = set()
    gain_workbooks: set[str] = set()
    loss_workbooks: set[str] = set()
    for group_rows in groups.values():
        left = statistics.fmean(float(row["metrics"][method]["top5"]) for row in group_rows)
        right = statistics.fmean(float(row["metrics"][baseline]["top5"]) for row in group_rows)
        diffs.append(left - right)
        for row in group_rows:
            if row["metrics"][method]["top5"] and not row["metrics"][baseline]["top5"]:
                gain_events.add(str(row["event_id"])); gain_workbooks.add(str(row["workbook_group"]))
            if row["metrics"][baseline]["top5"] and not row["metrics"][method]["top5"]:
                loss_events.add(str(row["event_id"])); loss_workbooks.add(str(row["workbook_group"]))
    return {
        "groups": len(groups),
        "mean_group_top5_difference": statistics.fmean(diffs) if diffs else None,
        "better_groups": sum(value > 0 for value in diffs),
        "equal_groups": sum(value == 0 for value in diffs),
        "worse_groups": sum(value < 0 for value in diffs),
        "gain_events": len(gain_events),
        "loss_events": len(loss_events),
        "net_event_gain": len(gain_events) - len(loss_events),
        "gain_workbooks": len(gain_workbooks),
        "loss_workbooks": len(loss_workbooks),
        "net_workbook_gain": len(gain_workbooks) - len(loss_workbooks),
    }


def risk_coverage(rows: Sequence[Mapping[str, object]], method: str) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for budget in range(1, REVIEW_BUDGET + 1):
        cloned: list[dict[str, object]] = []
        for row in rows:
            action = set(row["action_cells"].get(method, [])[:budget])
            set(row["source_formula_cells"])
            cloned.append({"case_kind": row["case_kind"], "source_formula_cells": row["source_formula_cells"], "action_cells": {method: list(action)}})
        summary = action_summary(cloned, method, "error")
        controls = action_summary(cloned, method, "control")
        output.append({"budget": budget, "error": summary, "control": controls})
    return output


def _permutation_check(rows: Sequence[Mapping[str, object]], method: str) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error" and row["source_formula_cells"]]
    if len(errors) < 2:
        return {"rounds": 0, "seed": PERMUTATION_SEED, "observed_hit_rate": None, "null_mean_hit_rate": None}
    # Permute source blocks within each cohort.  The action decisions never
    # see this permutation; it is a label-only placebo for the hit statistic.
    by_cohort: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in errors:
        by_cohort[str(row["cohort"])].append(row)
    rng = random.Random(PERMUTATION_SEED)
    observed = sum(_event_action(row, method)["hit"] for row in errors) / len(errors)
    null_values: list[float] = []
    for _ in range(PERMUTATION_ROUNDS):
        hits = 0
        total = 0
        for group_rows in by_cohort.values():
            source_sets = [list(row["source_formula_cells"]) for row in group_rows]
            rng.shuffle(source_sets)
            for row, sources in zip(group_rows, source_sets):
                actions = set(row["action_cells"].get(method, []))
                hits += int(bool(actions & set(sources)))
                total += 1
        null_values.append(hits / total if total else 0.0)
    return {
        "rounds": PERMUTATION_ROUNDS,
        "seed": PERMUTATION_SEED,
        "observed_hit_rate": observed,
        "null_mean_hit_rate": statistics.fmean(null_values),
        "null_p95_hit_rate": sorted(null_values)[int(0.95 * (len(null_values) - 1))],
        "observed_above_null_mean": observed > statistics.fmean(null_values),
        "action_rate_is_label_independent": True,
    }


def _serialize_event(row: Mapping[str, object]) -> dict[str, object]:
    output = {key: value for key, value in row.items() if key not in {"audit", "v4_rank"}}
    output["v4_rank"] = row["v4_rank"]
    return output


def score(*, profiles_path: Path, signal_dir: Path, v4_dir: Path, output_dir: Path) -> Path:
    profiles_path = profiles_path.resolve()
    signal_dir = signal_dir.resolve()
    v4_dir = v4_dir.resolve()
    output_dir = output_dir.resolve()
    profiles = read_profiles(profiles_path)
    profiles_hash = sha256(profiles_path)
    signal_receipt = _validate_signal_run(signal_dir, profiles, profiles_hash)
    v4_receipt = _validate_v4_run(v4_dir, profiles, profiles_hash)
    # Only this line crosses the prediction/scoring boundary.
    revealed_events, label_files = load_revealed_events()
    shards = _load_shards(signal_dir, v4_dir, profiles)
    rows = attach_events(revealed_events, profiles, shards)
    selected_rows, selected_channels = fixed_selector_rows(rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    event_path = output_dir / "event_scores.jsonl"
    event_bytes = "".join(
        json.dumps(_serialize_event(row), ensure_ascii=False, sort_keys=True) + "\n"
        for row in sorted(selected_rows, key=lambda item: str(item["event_id"]))
    ).encode("utf-8")
    write_immutable(event_path, event_bytes, description="Gate 2 event scores")

    cohorts = sorted({str(row["cohort"]) for row in rows})
    methods = ("v4", *CHANNELS, "oracle_union", "oracle_selector")
    summaries: dict[str, object] = {}
    for cohort in cohorts:
        cohort_rows = [row for row in rows if row["cohort"] == cohort]
        summaries[cohort] = {
            "events": len(cohort_rows),
            "errors": sum(row["case_kind"] == "error" for row in cohort_rows),
            "controls": sum(row["case_kind"] == "control" for row in cohort_rows),
            "methods": {
                method: {
                    "event_error": {key: value for key, value in _structure_macro(cohort_rows, method, "error").items()},
                    "event_control": {key: value for key, value in _structure_macro(cohort_rows, method, "control").items()},
                    "action_error": action_summary(cohort_rows, method, "error") if method in CHANNELS else None,
                    "action_control": action_summary(cohort_rows, method, "control") if method in CHANNELS else None,
                }
                for method in methods
            },
        }

    fixed_method_rows: list[dict[str, object]] = []
    for row in selected_rows:
        clone = dict(row)
        clone["metrics"] = dict(row["metrics"])
        clone["metrics"]["fixed_selector@5"] = row["selector_metrics"]
        clone["action_cells"] = dict(row["action_cells"])
        clone["action_cells"]["fixed_selector@5"] = row["action_cells"][row["selector_channel"]]
        fixed_method_rows.append(clone)
    all_methods = (*methods, "fixed_selector@5")
    overall = {
        method: {
            "error": _structure_macro(fixed_method_rows if method == "fixed_selector@5" else rows, method, "error") if method != "fixed_selector@5" else {
                "groups": len({row["structure_group"] for row in fixed_method_rows if row["case_kind"] == "error"}),
                "events": sum(row["case_kind"] == "error" for row in fixed_method_rows),
                **{key: statistics.fmean(float(row["selector_metrics"][key]) for row in fixed_method_rows if row["case_kind"] == "error") for key in ("top1", "top5", "mrr", "region_hit", "source_block_coverage")},
            },
            "action_error": action_summary(fixed_method_rows, method, "error") if method in CHANNELS or method == "fixed_selector@5" else None,
            "action_control": action_summary(fixed_method_rows, method, "control") if method in CHANNELS or method == "fixed_selector@5" else None,
        }
        for method in all_methods
    }
    fixed_by_cohort: dict[str, object] = {}
    for cohort in cohorts:
        cohort_rows = [row for row in fixed_method_rows if row["cohort"] == cohort]
        fixed_by_cohort[cohort] = {
            "error": {
                "groups": len({row["structure_group"] for row in cohort_rows if row["case_kind"] == "error"}),
                "events": sum(row["case_kind"] == "error" for row in cohort_rows),
                **{key: statistics.fmean(float(row["selector_metrics"][key]) for row in cohort_rows if row["case_kind"] == "error") if any(row["case_kind"] == "error" for row in cohort_rows) else None for key in ("top1", "top5", "mrr", "region_hit", "source_block_coverage")},
            },
            "action_error": action_summary(cohort_rows, "fixed_selector@5", "error"),
            "action_control": action_summary(cohort_rows, "fixed_selector@5", "control"),
        }

    gate2a: dict[str, object] = {}
    main_queues = ["enron", "public:integer_corpus", "public:modified_euses", "historical_100"]
    baseline_method = "v4"
    for cohort in main_queues:
        if cohort not in cohorts:
            continue
        fixed_rows = [row for row in fixed_method_rows if row["cohort"] == cohort]
        error_rows = [row for row in fixed_rows if row["case_kind"] == "error"]
        fixed_top5 = _fixed_macro(fixed_rows, "error")["top5"] if error_rows else None
        # Keep the comparison at the same cohort and structure-group level as
        # the fixed selector.  V4 is stored on the original rows, so construct
        # the corresponding group macro explicitly.
        v4_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in error_rows:
            v4_groups[str(row["structure_group"])].append(row)
        v4_group_values = [statistics.fmean(float(item["metrics"][baseline_method]["top5"]) for item in group_rows) for group_rows in v4_groups.values()]
        v4_top5 = statistics.fmean(v4_group_values) if v4_group_values else None
        gate2a[cohort] = {
            "fixed_selector_error_top5": fixed_top5,
            "v4_error_top5": v4_top5,
            "difference": fixed_top5 - v4_top5 if fixed_top5 is not None and v4_top5 is not None else None,
            "paired": _paired_diff(fixed_method_rows, "fixed_selector@5", baseline_method, cohort),
        }
    enron_fixed = [row for row in fixed_method_rows if row["cohort"] == "enron" and row["case_kind"] == "error"]
    enron_gains = {row["workbook_group"] for row in enron_fixed if row["selector_metrics"]["top5"] and not row["metrics"]["v4"]["top5"]}
    enron_losses = {row["workbook_group"] for row in enron_fixed if row["metrics"]["v4"]["top5"] and not row["selector_metrics"]["top5"]}
    fixed_all_errors = [row for row in fixed_method_rows if row["case_kind"] == "error"]
    v4_all_errors = [row for row in rows if row["case_kind"] == "error"]
    oracle_all = statistics.fmean(float(row["metrics"]["oracle_selector"]["top5"]) for row in v4_all_errors) if v4_all_errors else 0.0
    fixed_all = statistics.fmean(float(row["selector_metrics"]["top5"]) for row in fixed_all_errors) if fixed_all_errors else 0.0
    v4_all = statistics.fmean(float(row["metrics"]["v4"]["top5"]) for row in v4_all_errors) if v4_all_errors else 0.0
    headroom = oracle_all - v4_all
    gate2a["decision"] = {
        "enron_net_workbook_rescue_at_least_3": len(enron_gains) - len(enron_losses) >= 3,
        "enron_gain_workbooks": len(enron_gains), "enron_loss_workbooks": len(enron_losses),
        "fixed_recovers_half_oracle_headroom": (fixed_all - v4_all) / headroom >= 0.5 if headroom > 0 else False,
        "fixed_recovers_oracle_headroom_fraction": (fixed_all - v4_all) / headroom if headroom > 0 else None,
        "main_queue_drop_at_most_5pp": all(
            value.get("difference") is None or float(value["difference"]) >= -0.05
            for value in gate2a.values() if isinstance(value, dict) and "difference" in value
        ),
    }
    gate2a["decision"]["passed"] = all(gate2a["decision"].values())

    selective: dict[str, object] = {}
    for method in CHANNELS:
        selective[method] = {
            "all": {"error": action_summary(rows, method, "error"), "control": action_summary(rows, method, "control")},
            "risk_coverage": risk_coverage(rows, method),
            "label_permutation": _permutation_check(rows, method),
        }
    selective["fixed_selector@5"] = {
        "all": {"error": action_summary(fixed_method_rows, "fixed_selector@5", "error"), "control": action_summary(fixed_method_rows, "fixed_selector@5", "control")},
        "risk_coverage": risk_coverage(fixed_method_rows, "fixed_selector@5"),
        "label_permutation": _permutation_check(fixed_method_rows, "fixed_selector@5"),
    }
    fixed_action = selective["fixed_selector@5"]["all"]
    action_error = fixed_action["error"]
    action_control = fixed_action["control"]
    gate2b = {
        "acted_precision_at_least_75pct": (action_error["acted_precision"] or 0.0) >= 0.75,
        "error_source_action_coverage_at_least_30pct": (action_error["error_source_action_coverage"] or 0.0) >= 0.30,
        "control_action_rate_at_most_15pct": (action_control["action_rate"] or 0.0) <= 0.15,
        "baseline_v4_2_and_strong_comparison_available": False,
        "baseline_comparison_note": "Gate 2 scorer does not treat legacy V4.2 outputs as same-input predictions; a compatible re-run is required before a B pass can be claimed.",
    }
    gate2b["passed"] = all(bool(value) for key, value in gate2b.items() if key.endswith(("pct", "rate"))) and gate2b["baseline_v4_2_and_strong_comparison_available"]
    branch = "A" if gate2a["decision"]["passed"] else ("B" if gate2b["passed"] else "C")

    payload = {
        "protocol": SCORER_PROTOCOL,
        "scorer_version": "gate2-score-v1",
        "complete": True,
        "git_commit": git_commit(),
        "profiles": {"path": _relative(profiles_path), "sha256": sha256(profiles_path), "count": len(profiles)},
        "prediction_receipts": {
            "signal": {"path": _relative(signal_dir), "metadata_sha256": sha256(signal_dir / "metadata.json"), "complete_sha256": sha256(signal_dir / "complete.json"), "combined_shards_sha256": signal_receipt["complete"]["combined_shards_sha256"]},
            "v4": {"path": _relative(v4_dir), "metadata_sha256": sha256(v4_dir / "metadata.json"), "complete_sha256": sha256(v4_dir / "complete.json"), "combined_shards_sha256": v4_receipt["complete"]["combined_shards_sha256"]},
        },
        "revealed_label_files": [{"path": path, "sha256": sha256(ROOT / path)} for path in label_files],
        "label_boundary": {"prediction_label_inputs": [], "scoring_label_files_read_after_completion": label_files},
        "fixed_rules": {
            # Store JSON-native lists in the in-memory payload too, so a parsed
            # receipt compares equal on a deterministic rerun.
            "channels": list(CHANNELS), "selector_tie_order": list(SELECTOR_TIE_ORDER), "review_budget": REVIEW_BUDGET,
            "selector_training_objective": "leave_one_structure_group_out_error_structure_macro_top5_then_mrr",
            "action_definition": "top5_review_cells_with_status_evidence_supported_and_region_deduplication",
            "permutation_seed": PERMUTATION_SEED, "permutation_rounds": PERMUTATION_ROUNDS,
        },
        "event_count": len(rows),
        "cohort_summaries": summaries,
        "overall": overall,
        "fixed_selector": {"by_structure_group": selected_channels, "by_cohort": fixed_by_cohort},
        "leave_one_cohort_out": leave_one_cohort_out(rows),
        "gate2a": gate2a,
        "gate2b": gate2b,
        "selective": selective,
        "branch_decision": {"selected_branch": branch, "gate2a_passed": gate2a["decision"]["passed"], "gate2b_passed": gate2b["passed"], "gate2c_required": branch == "C"},
        "event_scores_sha256": sha256(event_path),
    }
    payload["receipt_sha256"] = stable_hash(payload)
    receipt_path = output_dir / "gate2_receipt.json"
    if receipt_path.exists():
        existing = _load_json(receipt_path)
        if existing != payload:
            raise ValueError("completed Gate 2 output exists with different content")
    else:
        temporary = receipt_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, receipt_path)
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNAL_RUN)
    parser.add_argument("--v4-baseline", type=Path, default=DEFAULT_V4_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        path = score(
            profiles_path=args.profiles,
            signal_dir=args.signals,
            v4_dir=args.v4_baseline,
            output_dir=args.output,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"model-discovery Gate 2 refused: {exc}") from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
