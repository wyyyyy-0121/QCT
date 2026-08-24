"""Generate the preregistered V6 synthetic layers with no external packages."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import normalized_formula
from formulaguard.workbook import WorkbookModel


ERROR_TYPES = (
    "reference_shift",
    "range_boundary",
    "operator",
    "function_replacement",
    "absolute_reference",
    "copy_offset",
)
TOPOLOGIES = ("chain", "fanout", "diamond", "cross_sheet", "mixed")
COMPLEXITIES = ("small", "medium", "large", "complex")
DEPTHS = ("shallow", "medium", "deep")
PROFILE_COUNTS = {
    "smoke": 24,
    "development": 1200,
    "validation": 360,
    "redteam": 360,
    "clean": 240,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _col_row(address: str) -> tuple[str, int]:
    index = 0
    while index < len(address) and address[index].isalpha():
        index += 1
    return address[:index], int(address[index:])


def _sheet_xml(cells: dict[str, object], formulas: dict[str, str]) -> str:
    rows: dict[int, list[str]] = {}
    for address, value in cells.items():
        _, row = _col_row(address)
        if isinstance(value, (int, float)):
            cell = f'<c r={quoteattr(address)}><v>{value}</v></c>'
        else:
            cell = f'<c r={quoteattr(address)} t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
        rows.setdefault(row, []).append(cell)
    for address, formula in formulas.items():
        _, row = _col_row(address)
        body = formula[1:] if formula.startswith("=") else formula
        rows.setdefault(row, []).append(f'<c r={quoteattr(address)}><f>{escape(body)}</f></c>')
    content = []
    for row, items in sorted(rows.items()):
        items.sort(key=lambda text: text.split('r="', 1)[1].split('"', 1)[0])
        content.append(f'<row r="{row}">' + "".join(items) + "</row>")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>' + "".join(content) + '</sheetData></worksheet>'
    )


def write_xlsx(path: Path, sheets: list[tuple[str, dict[str, object], dict[str, str]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, len(sheets) + 1)
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + overrides + '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    sheet_nodes = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{index}" r:id="rId{index}"/>'
        for index, (name, _, _) in enumerate(sheets, 1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>' + sheet_nodes + '</sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(sheets) + 1)
        ) + '</Relationships>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        for index, (_, cells, formulas) in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(cells, formulas))


@dataclass(frozen=True)
class Case:
    instance_id: str
    split: str
    error_type: str
    topology: str
    complexity: str
    depth: str
    template_family: str
    seed: int
    ambiguous: bool = False


def enumerate_cases(profile: str) -> list[Case]:
    cases: list[Case] = []
    if profile == "development":
        for error in ERROR_TYPES:
            for topology in TOPOLOGIES:
                for complexity in COMPLEXITIES:
                    for replicate in range(10):
                        cases.append(Case(
                            f"v6_dev_{len(cases)+1:04d}", profile, error, topology, complexity,
                            DEPTHS[replicate % 3], f"dev_{topology}_{complexity}_{replicate:02d}",
                            610_000 + len(cases),
                        ))
    elif profile in {"validation", "redteam"}:
        prefix = "val" if profile == "validation" else "red"
        for error in ERROR_TYPES:
            for topology in TOPOLOGIES:
                for depth in DEPTHS:
                    for template in range(4):
                        cases.append(Case(
                            f"v6_{prefix}_{len(cases)+1:04d}", profile, error, topology,
                            COMPLEXITIES[template], depth, f"{prefix}_{topology}_{depth}_{template}",
                            (620_000 if profile == "validation" else 630_000) + len(cases),
                            ambiguous=profile == "redteam",
                        ))
    elif profile == "smoke":
        for index in range(24):
            error = ERROR_TYPES[index % 6]
            topology = TOPOLOGIES[index % 5]
            cases.append(Case(
                f"v6_smoke_{index+1:03d}", profile, error, topology, COMPLEXITIES[index % 4],
                DEPTHS[index % 3], f"smoke_{index:02d}", 600_000 + index,
                ambiguous=index >= 18,
            ))
    return cases


def _qualified(sheet: str, address: str, cross_sheet: bool) -> str:
    return f"'{sheet}'!{address}" if cross_sheet else address


def build_case(case: Case, *, clean_only: bool = False):
    rng = random.Random(case.seed)
    scale = COMPLEXITIES.index(case.complexity) if case.complexity in COMPLEXITIES else 1
    split_offset = {"development": 0, "validation": 4, "redteam": 8, "smoke": 12, "clean": 16, "third_party": 20}.get(case.split, 0)
    last = 8 + scale * 3 + split_offset
    target_row = 4 + scale + split_offset
    cross = case.topology == "cross_sheet"
    data_sheet = "Inputs" if cross else "Model"
    input_cells: dict[str, object] = {"B1": round(0.03 + (case.seed % 7) / 100, 2)}
    for row in range(2, last + 1):
        input_cells[f"B{row}"] = 10 + rng.randrange(30)
        input_cells[f"C{row}"] = 5 + rng.randrange(20)
        input_cells[f"D{row}"] = 2 + rng.randrange(15)
    model_cells = {} if cross else dict(input_cells)
    for row in range(2, last + 1):
        shadow_target = input_cells if cross else model_cells
        shadow_target[f"Q{row}"] = 8 + rng.randrange(25)
        shadow_target[f"R{row}"] = 4 + rng.randrange(18)
        shadow_target[f"S{row}"] = 1 + rng.randrange(12)
    model_formulas: dict[str, str] = {}

    def ref(address: str) -> str:
        return _qualified(data_sheet, address, cross)

    def shadow_ref(address: str) -> str:
        return _qualified(data_sheet, address, cross)

    def correct_for(row: int) -> str:
        if case.error_type == "range_boundary":
            # Range cases intentionally mix aggregate functions while keeping
            # one shared boundary.  FFC alone is therefore ambiguous; BSS can
            # vote on endpoints independently of the outer function.
            function = "SUM" if row == target_row else ("SUM", "AVERAGE", "MIN", "MAX")[(row + case.seed) % 4]
            return f"={function}({ref(f'B{row}')}:{ref(f'D{row}')})"
        if case.error_type == "function_replacement":
            return f"=SUM({ref(f'B{row}')}:{ref(f'D{row}')})"
        if case.error_type == "copy_offset":
            return f"={ref(f'B{row}')}*{ref(f'C{row}')}+{ref(f'D{row}')}"
        if case.error_type == "absolute_reference":
            return f"={ref(f'B{row}')}*(1+{ref('$B$1')})+{ref(f'C{row}')}+{ref(f'D{row}')}"
        return f"={ref(f'B{row}')}+{ref(f'C{row}')}+{ref(f'D{row}')}"

    for row in range(2, last + 1):
        model_formulas[f"E{row}"] = correct_for(row)
        model_formulas[f"F{row}"] = f"=E{row}*2"

        # A second, legitimate local family deliberately uses the same shape as
        # the injected mutation.  This prevents a global rarity detector from
        # treating the error class itself as truth; only local family semantics
        # can distinguish the E-block from this valid T-block.
        if case.error_type == "reference_shift":
            shadow = f"={shadow_ref(f'Q{max(2, row-1)}')}+{shadow_ref(f'R{row}')}+{shadow_ref(f'S{row}')}"
        elif case.error_type == "range_boundary":
            shadow = f"=SUM({shadow_ref(f'Q{row}')}:{shadow_ref(f'R{row}')})"
        elif case.error_type == "operator":
            shadow = f"={shadow_ref(f'Q{row}')}+{shadow_ref(f'R{row}')}-{shadow_ref(f'S{row}')}"
        elif case.error_type == "function_replacement":
            shadow = f"=MIN({shadow_ref(f'Q{row}')}:{shadow_ref(f'S{row}')})"
        elif case.error_type == "absolute_reference":
            shadow = f"={shadow_ref(f'Q{row}')}*(1+{shadow_ref(f'Q{max(2, row-1)}')})+{shadow_ref(f'R{row}')}+{shadow_ref(f'S{row}')}"
        else:
            shadow = f"={shadow_ref(f'Q{max(2, row-1)}')}*{shadow_ref(f'R{row}')}+{shadow_ref(f'S{row}')}"
        model_formulas[f"T{row}"] = shadow
        model_formulas[f"U{row}"] = f"=T{row}*2"

    correct = correct_for(target_row)
    if case.error_type == "reference_shift":
        mutant = f"={ref(f'B{target_row-1}')}+{ref(f'C{target_row}')}+{ref(f'D{target_row}')}"
    elif case.error_type == "range_boundary":
        mutant = f"=SUM({ref(f'B{target_row}')}:{ref(f'C{target_row}')})"
    elif case.error_type == "operator":
        mutant = f"={ref(f'B{target_row}')}+{ref(f'C{target_row}')}-{ref(f'D{target_row}')}"
    elif case.error_type == "function_replacement":
        mutant = f"=MIN({ref(f'B{target_row}')}:{ref(f'D{target_row}')})"
    elif case.error_type == "absolute_reference":
        mutant = f"={ref(f'B{target_row}')}*(1+{ref(f'B{target_row-1}')})+{ref(f'C{target_row}')}+{ref(f'D{target_row}')}"
    else:
        mutant = f"={ref(f'B{target_row-1}')}*{ref(f'C{target_row}')}+{ref(f'D{target_row}')}"

    if not clean_only:
        model_formulas[f"E{target_row}"] = mutant
    if case.ambiguous:
        special_row = target_row + 2 if target_row + 2 <= last else target_row - 2
        model_formulas[f"E{special_row}"] = f"=MAX({ref(f'B{special_row}')}:{ref(f'D{special_row}')})"

    summary = last + 2
    if case.topology == "fanout":
        model_formulas[f"G{summary}"] = f"=SUM(E2:E{last})"
        model_formulas[f"G{summary+1}"] = f"=AVERAGE(E2:E{last})"
        model_formulas[f"G{summary+2}"] = f"=MAX(E2:E{last})"
        sink = f"G{summary}"
        base_depth = 1
    elif case.topology == "diamond":
        model_formulas[f"G{summary}"] = f"=SUM(E2:E{last})"
        model_formulas[f"G{summary+1}"] = f"=AVERAGE(E2:E{last})"
        model_formulas[f"H{summary+2}"] = f"=G{summary}+G{summary+1}"
        sink = f"H{summary+2}"
        base_depth = 2
    else:
        model_formulas[f"G{summary}"] = f"=SUM(F2:F{last})"
        sink = f"G{summary}"
        base_depth = 2
    if case.topology == "mixed":
        model_formulas[f"H{summary}"] = f"=AVERAGE(E2:E{last})"
        model_formulas[f"H{summary+1}"] = f"={sink}+H{summary}"
        sink = f"H{summary+1}"
        base_depth = 2

    target_depth = {"shallow": 2, "medium": 4, "deep": 7}[case.depth]
    for step in range(max(0, target_depth - base_depth)):
        address = f"R{summary + step}"
        model_formulas[address] = f"={sink}+1"
        sink = address

    # Legitimate heterogeneous blocks are intentional hard negatives.  They
    # model real workbooks containing departmental subtotals, rolling windows,
    # exception formulas, and secondary reporting chains.  They are identical
    # in clean/mutant pairs and therefore are not injected errors.
    special_count = 8 + scale * 4
    for item in range(special_count):
        row = summary + 8 + item
        range_start = 2 + (item % 3)
        range_end = max(range_start, last - (item % 4))
        aggregate = ("SUM", "AVERAGE", "MAX", "MIN")[item % 4]
        model_formulas[f"K{row}"] = f"={aggregate}(E{range_start}:E{range_end})"
        model_formulas[f"L{row}"] = f"=K{row}*(1+{ref('$B$1')})"
        model_formulas[f"M{row}"] = f"=L{row}+F{2 + (item * 3) % (last - 1)}"
        if item % 3 == 0:
            model_formulas[f"N{row}"] = f"=M{row}+K{row}"
    # A few correct, deliberately exceptional formulas prevent rarity from
    # becoming an error label.  Red-team cases add more ambiguity, but all
    # datasets contain at least some legitimate exceptions.
    exception_rows = 2 if not case.ambiguous else 5
    for item in range(exception_rows):
        row = summary + 8 + item
        model_formulas[f"P{row}"] = f"=MAX(K{row}:M{row})" if item % 2 == 0 else f"=MIN(K{row}:M{row})"

    # Split-specific side chains make graph+formula signatures disjoint without
    # changing the labeled propagation depth.
    split_tail = {"development": 1, "validation": 2, "redteam": 3, "smoke": 4, "third_party": 5}.get(case.split, 0)
    for offset in range(split_tail):
        address = f"J{summary + offset}"
        previous = f"J{summary + offset - 1}" if offset else "E2"
        model_formulas[address] = f"={previous}+E{2 + (case.seed + offset) % (last - 1)}"

    sheets = []
    if cross:
        sheets.append(("Inputs", input_cells, {}))
        sheets.append(("Model", model_cells, model_formulas))
    else:
        sheets.append(("Model", model_cells, model_formulas))
    return sheets, f"Model!E{target_row}", correct, mutant, f"Model!{sink}"


def clean_controls() -> list[Case]:
    structures = ("row_family", "column_family", "cross_sheet", "diamond", "mixed", "exception")
    cases = []
    for structure in structures:
        for complexity in COMPLEXITIES:
            for replicate in range(10):
                topology = "cross_sheet" if structure == "cross_sheet" else "diamond" if structure == "diamond" else "mixed" if structure in {"mixed", "exception"} else "chain"
                cases.append(Case(
                    f"v6_clean_{len(cases)+1:04d}", "clean", "function_replacement", topology,
                    complexity, DEPTHS[replicate % 3], f"clean_{structure}_{complexity}_{replicate}",
                    640_000 + len(cases), ambiguous=structure == "exception",
                ))
    return cases


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=tuple(PROFILE_COUNTS), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    root = args.output or Path("data") / f"v6_{args.profile}"
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty V6 dataset directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    cases = clean_controls() if args.profile == "clean" else enumerate_cases(args.profile)
    if args.limit:
        cases = cases[: args.limit]

    public, labels, clean_manifest, fingerprints = [], [], [], []
    for index, case in enumerate(cases, 1):
        if case.split == "clean":
            sheets, _, _, _, _ = build_case(case, clean_only=True)
            path = root / "clean" / f"{case.instance_id}.xlsx"
            write_xlsx(path, sheets)
            clean_manifest.append({
                "clean_id": case.instance_id,
                "structure": case.template_family.split("_")[1],
                "complexity": case.complexity,
                "workbook": path.relative_to(root).as_posix(),
                "sha256": sha256(path),
            })
        else:
            mutant_sheets, source, correct, mutant, sink = build_case(case)
            clean_sheets, _, _, _, _ = build_case(case, clean_only=True)
            clean_path = root / "clean" / f"{case.instance_id}.xlsx"
            mutant_path = root / "mutants" / f"{case.instance_id}.xlsx"
            write_xlsx(clean_path, clean_sheets)
            write_xlsx(mutant_path, mutant_sheets)
            model = WorkbookModel.from_xlsx(mutant_path)
            sheet, address = source.rsplit("!", 1)
            sink_sheet, sink_address = sink.rsplit("!", 1)
            graph = model.dependency_graph()
            actual_depth = graph.shortest_path_length((sheet, address), (sink_sheet, sink_address))
            public.append({
                "instance_id": case.instance_id,
                "template_family": case.template_family,
                "topology_id": case.topology,
                "complexity": case.complexity,
                "data_split": case.split,
                "seed": case.seed,
                "clean_workbook": clean_path.relative_to(root).as_posix(),
                "mutant_workbook": mutant_path.relative_to(root).as_posix(),
                "clean_sha256": sha256(clean_path),
                "mutant_sha256": sha256(mutant_path),
                "ambiguous_safety_case": case.ambiguous,
            })
            labels.append({
                "instance_id": case.instance_id,
                "source_cell": source,
                "correct_formula": correct,
                "mutated_formula": mutant,
                "sink_cell": sink,
                "mutation_type": case.error_type,
                "expected_depth": case.depth,
                "actual_depth": actual_depth,
            })
            fingerprints.append((case.error_type, normalized_formula(correct), normalized_formula(mutant)))
        if index % 50 == 0 or index == len(cases):
            print(f"[{index}/{len(cases)}] generated", flush=True)

    if public:
        write_jsonl(root / "instances.jsonl", public)
        write_jsonl(root / "evaluation_labels.jsonl", labels)
    else:
        (root / "instances.jsonl").write_text("", encoding="utf-8")
        (root / "evaluation_labels.jsonl").write_text("", encoding="utf-8")
    (root / "clean_manifest.json").write_text(json.dumps(clean_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = ["instance_id", "template_family", "topology_id", "complexity", "data_split", "mutant_workbook"]
    with (root / "dataset_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader(); writer.writerows(public)
    generator_hash = sha256(Path(__file__))
    manifest = {
        "name": "FormulaGuard-V6-SemanticBench",
        "profile": args.profile,
        "instances": len(public),
        "clean_workbooks": len(clean_manifest),
        "expected_count": PROFILE_COUNTS[args.profile] if not args.limit else len(cases),
        "limited_generation": bool(args.limit),
        "error_types": list(ERROR_TYPES),
        "topologies": list(TOPOLOGIES),
        "complexities": list(COMPLEXITIES),
        "generator": "scripts/build_v6_dataset.py",
        "generator_source_sha256": generator_hash,
        "seed_namespace": {
            "smoke": 600000, "development": 610000, "validation": 620000,
            "redteam": 630000, "clean": 640000,
        }[args.profile],
        "instances_sha256": sha256(root / "instances.jsonl"),
        "evaluation_labels_sha256": sha256(root / "evaluation_labels.jsonl"),
        "clean_manifest_sha256": sha256(root / "clean_manifest.json"),
        "dataset_summary_sha256": sha256(root / "dataset_summary.csv"),
        "label_isolation": "localizers read instances.jsonl and workbook paths only",
        "historical_100_excluded": True,
    }
    (root / "dataset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    completion = {
        "protocol": "v6_dataset_completion_receipt_v1",
        "complete": True,
        "profile": args.profile,
        "cases": len(cases),
        "generator_source_sha256": generator_hash,
        "dataset_manifest_sha256": sha256(root / "dataset_manifest.json"),
    }
    (root / "dataset_build_complete.json").write_text(
        json.dumps(completion, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(root / "dataset_manifest.json")


if __name__ == "__main__":
    main()
