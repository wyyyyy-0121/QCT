"""Fixed-region aggregate and subtotal experiments; no model imports."""

from __future__ import annotations

import hashlib
import json
import random

from scripts.build_v515_constraint_cases import FAMILIES, binding, broken, intended

KINDS = ("single", "joint_two", "joint_three", "ambiguous", "cancel_total", "cancel_subtotals",
         "legal_exception", "clean", "expired", "conflict", "numeric_collision", "budget")


def build_cases(seed, repeats):
    rng = random.Random(seed)
    cases = []
    for family in FAMILIES:
        for repeat in range(repeats):
            start, count = rng.randrange(3, 35), rng.randrange(6, 10)
            common = (rng.randrange(12, 90), rng.randrange(2, 8), rng.randrange(2, 10))
            for kind in KINDS:
                regions = 9 if kind == "budget" else 3 if kind == "joint_three" else 2 if kind.startswith("cancel_") else 1
                cells, formulas, errors, aggregates = [], [], [], []
                all_members, healthy_total, actual_total = [], 0.0, 0.0
                for region in range(regions):
                    sheet = f"Dept_{region + 1}"
                    reverse = region == 1 and kind.startswith("cancel_")
                    members, target_total = [], 0.0
                    for row in range(start, start + count):
                        b, c, d = common
                        if kind == "numeric_collision" and row == start:
                            if family in {"product", "ratio", "weighted"}:
                                c = 1
                            elif family in {"sum", "difference"}:
                                c = 0
                            else:
                                d = 0
                        good, value = intended(family, row, b, c, d)
                        bad, other = broken(family, row, b, c, d)
                        if reverse:
                            good, bad, value, other = bad, good, other, value
                        changed = kind != "clean" and (row == start or (kind in {"joint_two", "ambiguous"} and row == start + count - 1))
                        formula = bad if changed else good
                        actual = other if changed else value
                        # In an ambiguous case the last endpoint is an intentional
                        # exception; the first is erroneous. Equal deltas make the
                        # aggregate unable to identify which endpoint is wrong.
                        legal = kind == "legal_exception" or (kind == "ambiguous" and row == start + count - 1)
                        target_total += actual if legal else value
                        actual_total += actual
                        formulas.append([sheet, f"H{row}", formula])
                        cells.extend([[sheet, f"{col}{row}", val] for col, val in zip("BCD", (b, c, d), strict=True)])
                        members.append([sheet, f"H{row}"])
                        if changed and not legal:
                            errors.append({"sheet": sheet, "cell": f"H{row}", "expected_formula": good})
                    all_members.extend(members)
                    healthy_total += target_total
                    if kind == "cancel_subtotals":
                        # Every department subtotal covers the entire predeclared
                        # region, independent of the chosen corruption location.
                        aggregates.append({"id": f"department-{region + 1}", "members": members, "total": target_total})
                aggregates.insert(0, {"id": "organization-total", "members": all_members, "total": healthy_total})
                if kind == "conflict":
                    aggregates.append({**aggregates[0], "id": "conflicting-total", "total": healthy_total + 99})
                raw = {"cells": cells, "formulas": formulas}
                doc = {"issuer": "simulated-ledger", "workbook_binding": binding(raw),
                       "valid_from": "2026-09-01", "valid_until": "2026-09-02" if kind == "expired" else "2026-09-30",
                       "aggregates": aggregates}
                payload = json.dumps(doc, sort_keys=True).encode()
                cluster = hashlib.sha256(f"{seed}:{family}:{repeat}".encode()).hexdigest()[:24]
                case = "k" + hashlib.sha256(f"{cluster}:{kind}".encode()).hexdigest()[:24]
                decision = "no_action" if kind in {"clean", "legal_exception"} else "abstain" if kind in {"ambiguous", "cancel_total", "conflict"} else "detect_and_repair"
                label = {"case_id": case, "cluster_id": cluster, "family": family, "cohort": kind,
                         "decision": decision, "errors": errors, "truth_completeness": "complete",
                         "constraint_qualified": kind in {"single", "joint_two", "joint_three", "cancel_subtotals", "clean", "legal_exception"}}
                cases.append((case, raw, payload, {doc["issuer"]: hashlib.sha256(payload).hexdigest()}, label))
    return cases
