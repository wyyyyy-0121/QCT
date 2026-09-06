"""Deterministic scaling fixtures; expected arithmetic never calls the model."""

from __future__ import annotations

import hashlib
import random

from scripts.build_v515_constraint_cases import binding, broken, encode, intended


def build_case(count, family="product", kind="unique", seed="v517-development"):
    if count < 2:
        raise ValueError("at least two departments are required")
    rng = random.Random(f"{seed}:{count}:{family}:{kind}")
    cells, formulas, errors, aggregates = [], [], [], []
    total = 0.0
    groups = {0: ([], 0.0), 1: ([], 0.0)}
    common = (60, 3, 7)
    for region in range(count):
        sheet = f"Dept_{region:03d}"
        start = rng.randrange(3, 15)
        c = rng.randrange(2, 7)
        b, d = c * rng.randrange(8, 25), rng.randrange(2, 12)
        if kind == "ambiguous":
            b, c, d = common
        if kind == "fractional":
            b, c = 61, 3
        reverse = kind in {"mixed_subtotals", "mixed_total", "mixed_no_solution"} and region % 2 == 1
        members = []
        subtotal = 0.0
        for row in range(start, start + 6):
            good, value = intended(family, row, b, c, d)
            bad, other = broken(family, row, b, c, d)
            if reverse:
                good, bad, value, other = bad, good, other, value
            changed = row == start and kind != "clean"
            legal = kind == "ambiguous" and region != 0
            formulas.append([sheet, f"H{row}", bad if changed else good])
            cells.extend([[sheet, f"{col}{row}", val] for col, val in zip("BCD", (b, c, d), strict=True)])
            members.append([sheet, f"H{row}"])
            subtotal += other if changed and legal else value
            if changed and not legal:
                errors.append({"sheet": sheet, "cell": f"H{row}", "expected_formula": good})
        old_members, old_total = groups[region % 2]
        groups[region % 2] = (old_members + members, old_total + subtotal)
        total += subtotal
    all_members = [formula[:2] for formula in formulas]
    aggregates.append({"id": "organization-total", "members": all_members,
                       "total": total + (0.25 if kind in {"no_solution", "mixed_no_solution"} else 0)})
    if kind == "mixed_subtotals":
        for group, (members, subtotal) in groups.items():
            aggregates.append({"id": f"division-{group}", "members": members, "total": subtotal})
    raw = {"cells": cells, "formulas": formulas}
    document = {"issuer": "simulated-scaling-ledger", "workbook_binding": binding(raw),
                "valid_from": "2026-09-01", "valid_until": "2026-09-30", "aggregates": aggregates}
    payload = encode(document)
    approvals = {document["issuer"]: hashlib.sha256(payload).hexdigest()}
    label = {"count": count, "family": family, "kind": kind, "seed": seed, "errors": errors,
             "decision": "abstain" if kind in {"ambiguous", "no_solution", "mixed_no_solution"} else "no_action" if kind == "clean" else "repair"}
    return raw, payload, approvals, label
