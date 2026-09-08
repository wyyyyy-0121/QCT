"""Numeric scaling fixtures; business arithmetic does not import model inference."""

from __future__ import annotations

import hashlib
import math
import random

from scripts.build_v515_constraint_cases import binding, broken, encode, intended

FAMILIES = ("product", "ratio", "weighted")
KINDS = ("unique", "mixed_subtotals", "ambiguous", "cancel_total", "no_solution", "clean", "legal",
         "numeric_collision", "tolerance_boundary", "invalid_approval", "candidate_dependency", "weak_bounds")


def build_case(count, family="product", kind="unique", seed="v518-development"):
    if count < 2 or family not in FAMILIES or kind not in KINDS:
        raise ValueError("invalid numeric fixture specification")
    rng = random.Random(f"{seed}:{count}:{family}:{kind}")
    cells, formulas, errors, ledger = [], [], [], []
    groups = {0: ([], []), 1: ([], [])}
    starts = []
    for region in range(count):
        sheet = f"Dept_{region:03d}"
        start = rng.randrange(3, 15)
        starts.append(start)
        b, c, d = rng.randrange(101, 900)/10, rng.randrange(21, 70)/10, rng.randrange(11, 99)/10
        if kind in {"ambiguous", "cancel_total", "weak_bounds"}:
            b, c, d = 61.1, 3.1, 2.1
        if region == 0 and kind in {"numeric_collision", "tolerance_boundary"}:
            c = 1.0 if kind == "numeric_collision" else 1.0 + 1e-12
        reverse = kind in {"mixed_subtotals", "cancel_total", "weak_bounds"} and region % 2 == 1
        members, expected_values = [], []
        for row in range(start, start+6):
            good, value = intended(family, row, b, c, d)
            bad, other = broken(family, row, b, c, d)
            if reverse:
                good, bad, value, other = bad, good, other, value
            changed = row == start and kind != "clean" and (kind != "cancel_total" or region < 2)
            legal = kind == "legal" or (kind == "ambiguous" and region != 0)
            formulas.append([sheet, f"H{row}", bad if changed else good])
            cells.extend([[sheet, f"{col}{row}", value] for col, value in zip("BCD", (b,c,d), strict=True)])
            members.append([sheet, f"H{row}"])
            expected_values.append(other if changed and legal else value)
            if changed and not legal:
                errors.append({"sheet": sheet, "cell": f"H{row}", "expected_formula": good})
        group_members, group_values = groups[region % 2]
        groups[region % 2] = group_members + members, group_values + expected_values
        ledger.extend(expected_values)
    if kind == "candidate_dependency":
        target = ["Dept_001", f"B{starts[1]}"]
        value = next(r[2] for r in cells if r[:2] == target)
        cells = [r for r in cells if r[:2] != target]
        formulas.append([*target, f"={value}+0*'Dept_000'!H{starts[0]}"])
    total = math.fsum(ledger)
    if kind == "no_solution":
        total += 0.12345
    if kind == "weak_bounds":
        _, good_value = intended(family, 1, 61.1, 3.1, 2.1)
        _, bad_value = broken(family, 1, 61.1, 3.1, 2.1)
        total += (good_value-bad_value)/3
    aggregates = [{"id": "organization-total", "members": [r[:2] for r in formulas if r[1].startswith("H")], "total": total}]
    if kind == "mixed_subtotals":
        aggregates.extend({"id": f"division-{group}", "members": members, "total": math.fsum(values)}
                          for group, (members, values) in groups.items())
    raw = {"cells": cells, "formulas": formulas}
    document = {"issuer": "simulated-numeric-ledger", "workbook_binding": binding(raw),
                "valid_from": "2026-09-01", "valid_until": "2026-09-30", "aggregates": aggregates}
    payload = encode(document)
    approvals = {} if kind == "invalid_approval" else {document["issuer"]: hashlib.sha256(payload).hexdigest()}
    decision = "abstain" if kind in {"ambiguous", "cancel_total", "no_solution", "numeric_collision", "tolerance_boundary", "weak_bounds"} else "no_action" if kind in {"clean", "legal"} else "repair"
    label = {"count": count, "family": family, "kind": kind, "seed": seed, "errors": errors,
             "decision": decision, "cluster_id": hashlib.sha256(f"{seed}:{family}:{count}".encode()).hexdigest()[:24]}
    return raw, payload, approvals, label
