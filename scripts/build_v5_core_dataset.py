"""Generate the fresh FormulaGuard V5-Core data layers.

The generator is independent of the localizer.  It never imports V5-Core and
never filters a case because a candidate or ranker fails.  Public manifests
and evaluation labels are written separately so prediction commands can be
audited for label isolation.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import normalized_formula
from formulaguard.workbook import WorkbookModel
from scripts.build_v6_dataset import sha256, write_xlsx


ERROR_TYPES = (
    "range_boundary",
    "operator",
    "function_replacement",
    "copy_offset",
    "absolute_reference",
    "reference_shift",
)
TOPOLOGIES = ("chain", "fanout", "diamond", "cross_sheet", "mixed")
REGIMES = ("one_direction", "two_dimensional", "periodic", "mixed_exception")
COMPLEXITIES = ("small", "medium", "large", "complex")
PROFILE_COUNTS = {
    "smoke": 24,
    "pilot": 240,
    "development": 1200,
    "redteam": 360,
    "clean": 360,
    "validation": 480,
    "third_party": 600,
}
SEED_BASES = {
    "smoke": 710_000,
    "pilot": 720_000,
    "development": 730_000,
    "redteam": 740_000,
    "clean": 750_000,
    "validation": 760_000,
    "third_party": 770_000,
}


@dataclass(frozen=True)
class Case:
    instance_id: str
    split: str
    error_type: str
    topology: str
    regime: str
    complexity: str
    template_family: str
    seed: int
    ambiguity: str = "none"


def enumerate_cases(profile: str, *, secret_seed_offset: int = 0) -> list[Case]:
    cases: list[Case] = []
    base = SEED_BASES[profile] + secret_seed_offset
    if profile in {"development", "pilot"}:
        replicates = 10 if profile == "development" else 2
        for error in ERROR_TYPES:
            for topology in TOPOLOGIES:
                for regime in REGIMES:
                    for replicate in range(replicates):
                        index = len(cases)
                        cases.append(Case(
                            f"v5c_{'dev' if profile == 'development' else 'pilot'}_{index + 1:04d}",
                            profile, error, topology, regime,
                            COMPLEXITIES[replicate % len(COMPLEXITIES)],
                            f"{profile}_{topology}_{regime}_{replicate:02d}",
                            base + index,
                        ))
    elif profile == "validation":
        for error in ERROR_TYPES:
            for topology in TOPOLOGIES:
                for regime in REGIMES:
                    for template in range(4):
                        index = len(cases)
                        cases.append(Case(
                            f"v5c_val_{index + 1:04d}", profile, error, topology, regime,
                            COMPLEXITIES[template], f"locked_{topology}_{regime}_{template}",
                            base + index,
                        ))
    elif profile == "redteam":
        ambiguities = ("competing_family", "legitimate_summary", "near_tie")
        for error in ERROR_TYPES:
            for topology in TOPOLOGIES:
                for ambiguity in ambiguities:
                    for template in range(4):
                        index = len(cases)
                        cases.append(Case(
                            f"v5c_red_{index + 1:04d}", profile, error, topology,
                            # The four red-team templates are the four formula
                            # regimes.  Including len(cases) here advanced the
                            # index twice per template and silently produced
                            # only regimes 0 and 2, which the dataset audit
                            # correctly rejected as an incomplete factorial.
                            REGIMES[template],
                            COMPLEXITIES[template], f"red_{topology}_{ambiguity}_{template}",
                            base + index, ambiguity,
                        ))
    elif profile == "third_party":
        for error in ERROR_TYPES:
            for topology in TOPOLOGIES:
                for regime in REGIMES:
                    for template in range(5):
                        index = len(cases)
                        cases.append(Case(
                            f"v5c_tp_{index + 1:04d}", profile, error, topology, regime,
                            COMPLEXITIES[template % 4], f"third_party_{topology}_{regime}_{template}",
                            base + index,
                            "semi_manual" if template == 4 else "none",
                        ))
    elif profile == "smoke":
        for index in range(24):
            cases.append(Case(
                f"v5c_smoke_{index + 1:03d}", profile,
                ERROR_TYPES[index % 6], TOPOLOGIES[index % 5], REGIMES[index % 4],
                COMPLEXITIES[index % 4], f"smoke_{index:02d}", base + index,
                "legitimate_summary" if index >= 18 else "none",
            ))
    return cases


def clean_cases() -> list[Case]:
    structures = (
        "regular_row", "regular_column", "two_dimensional", "alternating",
        "subtotal", "grand_total", "cross_sheet", "rolling_window",
        "mixed_aggregate", "department_exception", "sparse_formula", "near_tie",
    )
    calibration: dict[str, list[Case]] = {structure: [] for structure in structures}
    held: dict[str, list[Case]] = {structure: [] for structure in structures}
    index = 0
    for structure in structures:
        for scale in range(3):
            for replicate in range(10):
                regime = REGIMES[(structures.index(structure) + scale) % 4]
                topology = TOPOLOGIES[(structures.index(structure) + replicate) % 5]
                case = Case(
                    f"v5c_clean_{index + 1:04d}", "clean", "function_replacement",
                    topology, regime, COMPLEXITIES[scale],
                    f"clean_{structure}_{scale}_{replicate}", SEED_BASES["clean"] + index,
                    structure,
                )
                local_index = scale * 10 + replicate
                (calibration if local_index % 3 != 2 else held)[structure].append(case)
                index += 1

    def interleave(groups: dict[str, list[Case]]) -> list[Case]:
        return [
            groups[structure][position]
            for position in range(max(len(rows) for rows in groups.values()))
            for structure in structures
            if position < len(groups[structure])
        ]

    return interleave(calibration) + interleave(held)


def clean_control_partition(case: Case) -> str:
    local_index = (case.seed - SEED_BASES["clean"]) % 30
    return "calibration" if local_index % 3 != 2 else "locked_control"


def _qualified(sheet: str, address: str, cross_sheet: bool) -> str:
    return f"'{sheet}'!{address}" if cross_sheet else address


def build_case(case: Case, *, clean_only: bool = False):
    rng = random.Random(case.seed)
    scale = COMPLEXITIES.index(case.complexity)
    # Labeled source rows occupy disjoint spaces across splits.  This is a
    # structural separation, not a metadata-only declaration, and prevents an
    # identical normalized correct/mutant formula pair from crossing splits.
    target_base = {
        "smoke": 5, "pilot": 12, "development": 24, "redteam": 42,
        "clean": 60, "validation": 82, "third_party": 104,
    }[case.split]
    target_row = target_base + scale
    last = target_row + 8 + 2 * scale
    cross = (
        case.ambiguity == "cross_sheet"
        if clean_only and case.split == "clean"
        else case.topology == "cross_sheet"
    )
    data_sheet = "Inputs" if cross else "Model"
    input_cells: dict[str, object] = {"B1": round(0.03 + (case.seed % 11) / 100, 2)}
    for row in range(2, last + 1):
        input_cells[f"B{row}"] = 10 + ((case.seed * 11 + row * 7) % 43)
        input_cells[f"C{row}"] = 5 + rng.randrange(23)
        input_cells[f"D{row}"] = 2 + rng.randrange(17)
        input_cells[f"Q{row}"] = 9 + rng.randrange(29)
        input_cells[f"R{row}"] = 3 + rng.randrange(19)
        input_cells[f"S{row}"] = 1 + rng.randrange(13)
        for offset, column in enumerate(("BA", "BB", "BC", "BD", "BE", "BF", "BG", "BH")):
            input_cells[f"{column}{row}"] = 4 + ((case.seed + row * 5 + offset * 11) % 31)
    model_cells = {} if cross else dict(input_cells)
    formulas: dict[str, str] = {}

    def ref(address: str) -> str:
        return _qualified(data_sheet, address, cross)

    def aggregate_for(row: int) -> str:
        if case.regime == "periodic":
            return "SUM" if row % 2 == 0 else "AVERAGE"
        if case.regime == "mixed_exception" and row in {2, last}:
            return "MAX" if row == 2 else "MIN"
        return "SUM"

    def correct_for(row: int, column: str = "E") -> str:
        shift = ord(column) - ord("E")
        left = chr(ord("B") + min(shift, 1))
        middle = chr(ord("C") + min(shift, 1))
        right = chr(ord("D") + min(shift, 1))
        if case.error_type in {"range_boundary", "function_replacement"}:
            return f"={aggregate_for(row)}({ref(f'{left}{row}')}:{ref(f'{right}{row}')})"
        if case.error_type == "copy_offset":
            return f"={ref(f'{left}{row}')}*{ref(f'{middle}{row}')}+{ref(f'{right}{row}')}"
        if case.error_type == "absolute_reference":
            return f"={ref(f'{left}{row}')}*(1+{ref('$B$1')})+{ref(f'{middle}{row}')}+{ref(f'{right}{row}')}"
        return f"={ref(f'{left}{row}')}+{ref(f'{middle}{row}')}+{ref(f'{right}{row}')}"

    main_columns = ("E", "H") if case.regime == "two_dimensional" else ("E",)
    for row in range(2, last + 1):
        for column in main_columns:
            formulas[f"{column}{row}"] = correct_for(row, column)
            downstream_col = chr(ord(column) + 1)
            formulas[f"{downstream_col}{row}"] = f"={column}{row}*2"

    source_address = f"E{target_row}"
    correct = formulas[source_address]
    if case.error_type == "range_boundary":
        mutant = f"={aggregate_for(target_row)}({ref(f'B{target_row}')}:{ref(f'C{target_row}')})"
    elif case.error_type == "operator":
        mutant = f"={ref(f'B{target_row}')}+{ref(f'C{target_row}')}-{ref(f'D{target_row}')}"
    elif case.error_type == "function_replacement":
        wrong = "MIN" if aggregate_for(target_row) != "MIN" else "MAX"
        mutant = f"={wrong}({ref(f'B{target_row}')}:{ref(f'D{target_row}')})"
    elif case.error_type == "copy_offset":
        mutant = f"={ref(f'B{target_row - 1}')}*{ref(f'C{target_row}')}+{ref(f'D{target_row}')}"
    elif case.error_type == "absolute_reference":
        mutant = f"={ref(f'B{target_row}')}*(1+{ref(f'B{target_row - 1}')})+{ref(f'C{target_row}')}+{ref(f'D{target_row}')}"
    else:
        mutant = f"={ref(f'B{target_row - 1}')}+{ref(f'C{target_row}')}+{ref(f'D{target_row}')}"
    if not clean_only:
        formulas[source_address] = mutant

    # A legitimate competing block makes mutation syntax itself non-labeling.
    for row in range(2, last + 1):
        formulas[f"T{row}"] = (
            f"=MIN({ref(f'Q{row}')}:{ref(f'S{row}')})"
            if row % 3 == 0 else
            f"={ref(f'Q{max(2, row - 1)}')}+{ref(f'R{row}')}+{ref(f'S{row}')}"
        )
        formulas[f"U{row}"] = f"=T{row}*2"

    summary = last + 3
    if case.topology == "fanout":
        formulas[f"G{summary}"] = f"=SUM(E2:E{last})"
        formulas[f"G{summary + 1}"] = f"=AVERAGE(E2:E{last})"
        formulas[f"G{summary + 2}"] = f"=MAX(E2:E{last})"
        sink = f"G{summary}"
    elif case.topology == "diamond":
        formulas[f"G{summary}"] = f"=SUM(E2:E{last})"
        formulas[f"G{summary + 1}"] = f"=AVERAGE(E2:E{last})"
        formulas[f"H{summary + 2}"] = f"=G{summary}+G{summary + 1}"
        sink = f"H{summary + 2}"
    else:
        formulas[f"G{summary}"] = f"=SUM(F2:F{last})"
        sink = f"G{summary}"
    if case.topology == "mixed":
        formulas[f"J{summary}"] = f"=MAX(E2:E{last})"
        formulas[f"J{summary + 1}"] = f"={sink}+J{summary}"
        sink = f"J{summary + 1}"

    # Correct summaries and exceptions are deliberately retained in all sets.
    exception_count = 8 if case.split != "redteam" else 14
    for index in range(exception_count):
        row = summary + 6 + index
        start = 2 + index % 3
        end = last - index % 4
        function = ("SUM", "AVERAGE", "MAX", "MIN")[index % 4]
        formulas[f"K{row}"] = f"={function}(E{start}:E{end})"
        formulas[f"L{row}"] = f"=K{row}*(1+{ref('$B$1')})"
        if index % 2 == 0:
            formulas[f"M{row}"] = f"=MAX(K{row}:L{row})"
    if case.ambiguity in {"legitimate_summary", "subtotal", "grand_total", "department_exception"}:
        special_row = min(last, target_row + 2)
        formulas[f"P{summary}"] = f"=MAX(E2:E{special_row})"
        formulas[f"P{summary + 1}"] = f"=MIN(E{special_row}:E{last})"
    if case.ambiguity in {"competing_family", "near_tie"}:
        special_row = target_row + 2 if target_row + 2 <= last else target_row - 2
        formulas[f"E{special_row}"] = f"=MAX({ref(f'B{special_row}')}:{ref(f'D{special_row}')})"

    # Clean controls use an explicit W:AB probe block so the twelve declared
    # structures are observable in the formulas themselves, not just metadata.
    if clean_only and case.split == "clean":
        structure = case.ambiguity
        if structure == "regular_row":
            for output, left, right in zip(
                ("W", "X", "Y", "Z", "AA", "AB"),
                ("BA", "BB", "BC", "BD", "BE", "BF"),
                ("BB", "BC", "BD", "BE", "BF", "BG"),
            ):
                formulas[f"{output}2"] = f"={ref(f'{left}2')}+{ref(f'{right}2')}"
        elif structure in {"regular_column", "cross_sheet"}:
            for row in range(2, 14):
                formulas[f"W{row}"] = f"={ref(f'BA{row}')}+{ref(f'BB{row}')}"
        elif structure == "two_dimensional":
            for row in range(2, 8):
                for output, left, right in (("W", "BA", "BB"), ("X", "BB", "BC"), ("Y", "BC", "BD")):
                    formulas[f"{output}{row}"] = f"={ref(f'{left}{row}')}+{ref(f'{right}{row}')}"
        elif structure == "alternating":
            for row in range(2, 14):
                formulas[f"W{row}"] = (
                    f"=SUM({ref(f'BA{row}')}:{ref(f'BC{row}')})"
                    if row % 2 == 0 else
                    f"=MAX({ref(f'BA{row}')}:{ref(f'BC{row}')})"
                )
        elif structure == "subtotal":
            for row in (2, 5, 8):
                formulas[f"W{row}"] = f"=SUM({ref(f'BA{row}')}:{ref(f'BA{row + 2}')})"
            formulas["X2"] = "=W2+W5+W8"
        elif structure == "grand_total":
            for row in range(2, 10):
                formulas[f"W{row}"] = f"={ref(f'BA{row}')}+{ref(f'BB{row}')}"
            formulas["X2"] = "=SUM(W2:W9)"
        elif structure == "rolling_window":
            for row in range(4, 14):
                formulas[f"W{row}"] = f"=SUM({ref(f'BA{row - 2}')}:{ref(f'BA{row}')})"
        elif structure == "mixed_aggregate":
            functions = ("SUM", "AVERAGE", "MIN", "MAX")
            for offset, row in enumerate(range(2, 14)):
                function = functions[offset % len(functions)]
                formulas[f"W{row}"] = f"={function}({ref(f'BA{row}')}:{ref(f'BC{row}')})"
        elif structure == "department_exception":
            for row in range(2, 14):
                function = "MAX" if row in {6, 10} else "SUM"
                formulas[f"W{row}"] = f"={function}({ref(f'BA{row}')}:{ref(f'BC{row}')})"
            formulas["X2"] = "=SUM(W2:W5)"
            formulas["X6"] = "=SUM(W6:W9)"
            formulas["X10"] = "=SUM(W10:W13)"
        elif structure == "sparse_formula":
            for row in (2, 5, 8, 11):
                formulas[f"W{row}"] = f"={ref(f'BA{row}')}+{ref(f'BB{row}')}"
        elif structure == "near_tie":
            for row in range(2, 10):
                formulas[f"W{row}"] = f"=SUM({ref(f'BA{row}')}:{ref(f'BC{row}')})"
                formulas[f"X{row}"] = f"=AVERAGE({ref(f'BA{row}')}:{ref(f'BC{row}')})"

    sheets = []
    if cross:
        sheets.append(("Inputs", input_cells, {}))
        sheets.append(("Model", model_cells, formulas))
    else:
        sheets.append(("Model", model_cells, formulas))
    return sheets, f"Model!{source_address}", correct, mutant, f"Model!{sink}"


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=tuple(PROFILE_COUNTS), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--secret-seed-offset", type=int, default=0)
    args = parser.parse_args()
    if args.profile == "third_party":
        raise SystemExit(
            "Final third-party cases cannot be generated by the project; "
            "use the external preparation protocol"
        )
    root = args.output or Path("data") / f"v5_core_{args.profile}"
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty V5-Core dataset directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    cases = clean_cases() if args.profile == "clean" else enumerate_cases(
        args.profile, secret_seed_offset=args.secret_seed_offset,
    )
    if args.limit:
        cases = cases[: args.limit]

    public: list[dict] = []
    labels: list[dict] = []
    clean_manifest: list[dict] = []
    fingerprints: list[dict] = []
    for index, case in enumerate(cases, 1):
        if case.split == "clean":
            sheets, _, _, _, _ = build_case(case, clean_only=True)
            path = root / "clean" / f"{case.instance_id}.xlsx"
            write_xlsx(path, sheets)
            clean_manifest.append({
                "clean_id": case.instance_id,
                "structure": case.ambiguity,
                "control_partition": clean_control_partition(case),
                "regime": case.regime,
                "complexity": case.complexity,
                "template_family": case.template_family,
                "workbook": path.relative_to(root).as_posix(),
                "sha256": sha256(path),
            })
        else:
            mutant_sheets, source, correct, mutant, sink = build_case(case)
            clean_sheets, _, _, _, _ = build_case(case, clean_only=True)
            mutant_path = root / "mutants" / f"{case.instance_id}.xlsx"
            original_path = root / "originals" / f"{case.instance_id}.xlsx"
            write_xlsx(mutant_path, mutant_sheets)
            write_xlsx(original_path, clean_sheets)
            model = WorkbookModel.from_xlsx(mutant_path)
            source_sheet, source_address = source.rsplit("!", 1)
            sink_sheet, sink_address = sink.rsplit("!", 1)
            depth = model.dependency_graph().shortest_path_length(
                (source_sheet, source_address), (sink_sheet, sink_address),
            )
            public.append({
                "instance_id": case.instance_id,
                "template_family": case.template_family,
                "topology_id": case.topology,
                "regime": case.regime,
                "complexity": case.complexity,
                "data_split": case.split,
                "mutant_workbook": mutant_path.relative_to(root).as_posix(),
                "mutant_sha256": sha256(mutant_path),
                "ambiguity": case.ambiguity,
            })
            labels.append({
                "instance_id": case.instance_id,
                "original_workbook": original_path.relative_to(root).as_posix(),
                "original_sha256": sha256(original_path),
                "source_cell": source,
                "correct_formula": correct,
                "mutated_formula": mutant,
                "mutation_type": case.error_type,
                "sink_cell": sink,
                "actual_depth": depth,
            })
            fingerprints.append({
                "instance_id": case.instance_id,
                "correct": normalized_formula(correct),
                "mutant": normalized_formula(mutant),
            })
        if index % 50 == 0 or index == len(cases):
            print(f"[{index}/{len(cases)}] generated", flush=True)

    if public:
        write_jsonl(root / "instances.jsonl", public)
        write_jsonl(root / "evaluation_labels.jsonl", labels)
        write_jsonl(root / "formula_pairs.jsonl", fingerprints)
    if clean_manifest:
        (root / "clean_manifest.json").write_text(
            json.dumps(clean_manifest, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    manifest = {
        "model_family": "FormulaGuard V5-Core",
        "profile": args.profile,
        "expected_count": PROFILE_COUNTS[args.profile],
        "actual_count": len(cases),
        "subset_limit": args.limit,
        "error_types": list(ERROR_TYPES),
        "topologies": list(TOPOLOGIES),
        "regimes": list(REGIMES),
        "secret_seed_offset_recorded": args.secret_seed_offset if args.profile != "third_party" else "withheld",
        "generator_independent_of_localizer": True,
        "cases": [asdict(case) for case in cases] if args.profile != "third_party" else [],
    }
    (root / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    completion_inputs = [root / "dataset_manifest.json"]
    if public:
        completion_inputs.extend([root / "instances.jsonl", root / "evaluation_labels.jsonl"])
    if clean_manifest:
        completion_inputs.append(root / "clean_manifest.json")
    completion = {
        "complete": True,
        "profile": args.profile,
        "instances": len(cases),
        "manifest_hashes": {path.name: sha256(path) for path in completion_inputs},
        "model_results_consulted": False,
        "cases_excluded_for_model_failure": 0,
    }
    (root / "dataset_build_complete.json").write_text(
        json.dumps(completion, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(root / "dataset_manifest.json")


if __name__ == "__main__":
    main()
