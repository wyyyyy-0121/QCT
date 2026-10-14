"""Independent arithmetic-grid generator; imports no model or prediction code.

New seeded grids test this mechanism, not unseen natural spreadsheet semantics.
Legal operator exceptions intentionally test the limits of structural evidence.
"""

from __future__ import annotations

import hashlib
import random

FAMILIES = ("product", "ratio", "sum", "difference", "range", "weighted")
KINDS = ("edge_operator", "edge_reference", "clean", "legal_discount", "legal_constant",
         "legal_operator", "single_axis", "short", "systematic", "no_anchors", "conflicting_axes")


def formula(family, col, row):
    a, b = f"Inputs!{col}{row}", f"Inputs!{col}$2"
    if family == "product":
        return f"={a}*{b}"
    if family == "ratio":
        return f"={a}/{b}"
    if family == "sum":
        return f"={a}+{b}"
    if family == "difference":
        return f"={a}-{b}"
    if family == "range":
        return f"=SUM(Inputs!{col}{row}:{col}{row + 2})"
    return f"=({a}*{b}+{a})/{b}"


def mutate(value, family, col, row, reference=False):
    if reference or family == "range":
        return value.replace(f"{col}{row}", f"{col}{row + 1}", 1)
    op = {"product": "*", "ratio": "/", "sum": "+", "difference": "-", "weighted": "*"}[family]
    return value.replace(op, {"*": "/", "/": "*", "+": "-", "-": "+"}[op], 1)


def build_cases(seed: str, repeats: int):
    rng = random.Random(seed)
    output = []
    for family in FAMILIES:
        for repeat in range(repeats):
            start_row = rng.randrange(5, 35)
            height, width = rng.randrange(6, 11), rng.randrange(4, 8)
            first_col = rng.randrange(5, 12)
            all_cols = [chr(65 + first_col + i) for i in range(width)]
            all_rows = list(range(start_row, start_row + height))
            corner = (rng.choice((0, -1)), rng.choice((0, -1)))
            for kind in KINDS:
                cols = all_cols[:1] if kind in {"single_axis", "systematic", "no_anchors"} else all_cols
                rows = all_rows[:2] if kind == "short" else all_rows
                col, row = cols[corner[0]], rows[corner[1]]
                formulas = [["Data", f"{c}{r}", formula(family, c, r)] for r in rows for c in cols]
                cells = [["Inputs", f"{c}{r}", rng.randrange(2, 99)] for c in cols for r in [2, *range(rows[0], rows[-1] + 4)]]
                errors, decision = [], "no_action"
                if kind in {"edge_operator", "edge_reference", "single_axis"}:
                    decision = "detect_and_repair"
                elif kind in {"short", "systematic", "no_anchors", "conflicting_axes"}:
                    decision = "abstain"
                for entry in formulas:
                    target = entry[1] == f"{col}{row}"
                    r = int(entry[1][1:])
                    c = entry[1][0]
                    if kind == "systematic":
                        target = rows[1] <= r <= rows[-2]
                    if kind == "no_anchors":
                        target = True
                    if not target or kind == "clean":
                        continue
                    original = entry[2]
                    if kind == "legal_discount":
                        entry[2] = f"=({original[1:]})*0.9"
                    elif kind == "legal_constant":
                        entry[2] = f"=({original[1:]})+7"
                    else:
                        entry[2] = mutate(original, family, c, r, kind == "edge_reference")
                    if decision != "no_action":
                        errors.append({"sheet": "Data", "cell": entry[1], "expected_formula": original})
                if kind == "conflicting_axes":
                    # The horizontal anchors imply an incompatible candidate.
                    for entry in formulas:
                        if entry[1] != f"{col}{row}" and int(entry[1][1:]) == row:
                            entry[2] = "=(" + entry[2][1:] + ")+3"
                key = f"{seed}:{family}:{repeat}:{kind}"
                case_id = "k" + hashlib.sha256(key.encode()).hexdigest()[:24]
                cluster = "k" + hashlib.sha256(f"{seed}:{family}:{repeat}".encode()).hexdigest()[:24]
                output.append((case_id, {"cells": cells, "formulas": formulas}, {
                    "case_id": case_id, "cluster_id": cluster, "family": family,
                    "cohort": kind, "decision": decision, "errors": errors,
                    "truth_completeness": "complete",
                    "truth_basis": "declared synthetic intent; legal_operator is an identifiability stress case",
                }))
    return output
