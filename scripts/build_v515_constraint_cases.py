"""Generate simulated ledger/workbook pairs without importing model code.

Ledger totals use direct business arithmetic, not model evaluation or formula
answers. Approved source correctness is a declared synthetic assumption.
"""

from __future__ import annotations

import hashlib
import json
import random

FAMILIES = ("product", "ratio", "sum", "difference", "weighted", "range")
KINDS = ("error", "legal_exception", "no_approval", "expired", "wrong_binding",
         "conflict", "numeric_collision", "multiple_errors", "missing_input", "clean")


def intended(family, row, b, c, d):
    if family == "product":
        return f"=B{row}*C{row}", b * c
    if family == "ratio":
        return f"=B{row}/C{row}", b / c
    if family == "sum":
        return f"=B{row}+C{row}", b + c
    if family == "difference":
        return f"=B{row}-C{row}", b - c
    if family == "weighted":
        return f"=B{row}*C{row}+D{row}", b * c + d
    return f"=SUM(B{row}:D{row})", b + c + d


def broken(family, row, b, c, d):
    if family in {"product", "weighted"}:
        return f"=B{row}/C{row}" + (f"+D{row}" if family == "weighted" else ""), b / c + (d if family == "weighted" else 0)
    if family == "ratio":
        return f"=B{row}*C{row}", b * c
    if family == "sum":
        return f"=B{row}-C{row}", b - c
    if family == "difference":
        return f"=B{row}+C{row}", b + c
    return f"=SUM(B{row}:C{row})", b + c


def encode(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


def binding(raw):
    return hashlib.sha256(encode({k: sorted(v) for k, v in raw.items()})).hexdigest()


def build_cases(seed, repeats):
    rng = random.Random(seed)
    cases = []
    for family in FAMILIES:
        for repeat in range(repeats):
            start, count = rng.randrange(3, 40), rng.randrange(6, 12)
            indices = list(range(start, start + count))
            numbers = {r: (rng.randrange(12, 90), rng.randrange(2, 9), rng.randrange(2, 12)) for r in indices}
            peer_inputs = {r: tuple(rng.randrange(2, 12) for _ in range(3)) for r in indices}
            endpoint = rng.choice((indices[0], indices[-1]))
            pair_id = hashlib.sha256(f"{seed}:{family}:{repeat}".encode()).hexdigest()[:24]
            for kind in KINDS:
                values = dict(numbers)
                if kind == "numeric_collision":
                    b, c, d = values[endpoint]
                    if family in {"product", "ratio", "weighted"}:
                        c = 1
                    elif family in {"sum", "difference"}:
                        c = 0
                    else:
                        d = 0
                    values[endpoint] = b, c, d
                formulas, cells, errors, ledger_values, actual_values = [], [], [], [], []
                corrupt = {endpoint} if kind != "clean" else set()
                if kind == "multiple_errors":
                    corrupt = {indices[0], indices[-1]}
                for row in indices:
                    b, c, d = values[row]
                    healthy, expected = intended(family, row, b, c, d)
                    wrong, wrong_value = broken(family, row, b, c, d)
                    formulas.append(["Data", f"H{row}", wrong if row in corrupt else healthy])
                    cells.extend([["Data", f"{col}{row}", value] for col, value in zip("BCD", (b, c, d), strict=True)])
                    cells.extend([["Data", f"{col}{row}", value] for col, value in zip("EFG", peer_inputs[row], strict=True)])
                    for out_col, source_cols in (("I", "CDE"), ("J", "DEF"), ("K", "EFG")):
                        formulas.append(["Data", f"{out_col}{row}", healthy.translate(str.maketrans("BCD", source_cols))])
                    ledger_values.append(expected)
                    actual_values.append(wrong_value if row in corrupt else expected)
                    if row in corrupt and kind != "legal_exception":
                        errors.append({"sheet": "Data", "cell": f"H{row}", "expected_formula": healthy})
                if kind == "missing_input":
                    cells = [cell for cell in cells if cell[1] != f"B{endpoint}"]
                raw = {"cells": cells, "formulas": formulas}
                total = sum(actual_values) if kind == "legal_exception" else sum(ledger_values)
                document = {"issuer": "simulated-external-ledger", "workbook_binding": binding(raw),
                            "valid_from": "2026-09-01", "valid_until": "2026-09-30",
                            "aggregates": [{"id": "business-total", "members": [["Data", f"H{r}"] for r in indices], "total": total}]}
                if kind == "expired":
                    document["valid_until"] = "2026-09-02"
                if kind == "wrong_binding":
                    document["workbook_binding"] = "mismatched-workbook"
                if kind == "conflict":
                    document["aggregates"].append({**document["aggregates"][0], "id": "conflicting-total", "total": total + 99})
                payload = encode(document)
                approvals = {} if kind == "no_approval" else {document["issuer"]: hashlib.sha256(payload).hexdigest()}
                case = "k" + hashlib.sha256(f"{pair_id}:{kind}".encode()).hexdigest()[:24]
                decision = "no_action" if kind in {"clean", "legal_exception"} else "detect_and_repair"
                label = {"case_id": case, "cluster_id": pair_id, "pair_id": pair_id,
                         "cohort": kind, "family": family, "decision": decision, "errors": errors,
                         "truth_completeness": "complete", "constraint_qualified": kind in {"error", "legal_exception", "clean"}}
                cases.append((case, raw, payload, approvals, label))
    return cases
