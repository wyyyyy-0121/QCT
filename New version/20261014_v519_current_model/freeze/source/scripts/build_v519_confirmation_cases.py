"""V519 declared cohorts with independent business arithmetic and true coupling."""

import hashlib
import math

from scripts.build_v515_constraint_cases import binding, broken, encode, intended
from scripts.build_v518_numeric_cases import build_case as independent_case

FAMILIES = ("product", "ratio", "weighted")
KINDS = ("pair", "chain", "fan_in", "shared_bridge", "candidate_only", "coupled_ambiguous",
         "coupled_no_solution", "oversized_component", "independent_unique", "weak_bounds",
         "invalid_approval", "original_satisfies")


def build_case(count, family, kind, seed):
    if family not in FAMILIES or kind not in (*KINDS, "component8") or count < 4:
        raise ValueError("invalid V519 fixture")
    if kind in {"independent_unique", "weak_bounds", "original_satisfies"}:
        mapped = {"independent_unique":"unique", "weak_bounds":"weak_bounds", "original_satisfies":"cancel_total"}[kind]
        raw, document, approvals, label = independent_case(count, family, mapped, seed)
        return raw, document, approvals, {**label, "kind":kind}
    if kind in {"oversized_component", "component8"} and count < 9:
        raise ValueError("component pressure requires at least nine candidates")
    raw, _, _, label = independent_case(count, family, "unique", f"{seed}:{kind}")
    if kind == "coupled_ambiguous":
        for row in raw["cells"]:
            row[2] = {"B":61.1, "C":3.1, "D":2.1}[row[1][0]]
    first = [next(r for r in raw["formulas"] if r[0] == f"Dept_{i:03d}") for i in range(count)]
    links = {1:(0,)}
    if kind == "chain":
        links = {1:(0,), 2:(1,)}
    elif kind == "fan_in":
        links = {2:(0,1)}
    elif kind == "shared_bridge":
        links = {2:(0,1), 3:(0,1)}
    elif kind in {"oversized_component", "component8"}:
        links = {i:(i-1,) for i in range(1, 9 if kind == "oversized_component" else 8)}
    constants = {tuple(r[:2]):r[2] for r in raw["cells"]}
    expected_first, ledger, retained_errors = {}, [], []
    for index, (sheet, address, _) in enumerate(first):
        start = int(address[1:])
        b, c, d = (constants[(sheet, f"{col}{start}")] for col in "BCD")
        if index in links:
            refs = "+".join(f"'{first[j][0]}'!{first[j][1]}" for j in links[index])
            upstream = expected_first[links[index][0]]
            if len(links[index]) == 2:
                upstream += expected_first[links[index][1]]
            if kind == "shared_bridge":
                refs = "'Bridge'!A1"
            target_col, coefficient = ("C",0.001) if kind == "candidate_only" else ("B",0.125)
            target = [sheet, f"{target_col}{start}"]
            base = c if target_col == "C" else b
            raw["cells"] = [r for r in raw["cells"] if r[:2] != target]
            raw["formulas"].append([*target, f"={base}+{coefficient}*({refs})"])
            if target_col == "C":
                c += coefficient*upstream
                raw["cells"].append([sheet, f"E{start}", 1.0])
                replacement = f"=B{start}{'/' if family == 'ratio' else '*'}E{start}" + (f"+D{start}" if family == "weighted" else "")
                next(r for r in raw["formulas"] if r[:2] == [sheet,address])[2] = replacement
            else:
                b += coefficient*upstream
        legal_exception = kind == "coupled_ambiguous" and index >= 3
        expected_first[index] = (broken if legal_exception else intended)(family,start,b,c,d)[1]
        if not legal_exception:
            retained_errors.append({"sheet":sheet, "cell":address, "expected_formula":intended(family,start,b,c,d)[0]})
        for offset in range(6):
            row = start+offset
            value = expected_first[index] if offset == 0 else intended(family,row,
                *(constants[(sheet,f"{col}{row}")] for col in "BCD"))[1]
            ledger.append(([sheet,f"H{row}"],value))
    if kind == "shared_bridge":
        raw["formulas"].append(["Bridge","A1",f"='{first[0][0]}'!{first[0][1]}+'{first[1][0]}'!{first[1][1]}"])
        ledger.append((["Bridge","A1"],expected_first[0]+expected_first[1]))
    total = math.fsum(value for _,value in ledger)
    if kind == "coupled_no_solution":
        total += 0.12345
    document = {"issuer":"simulated-v519-ledger", "workbook_binding":binding(raw),
                "valid_from":"2026-09-01", "valid_until":"2026-09-30", "aggregates":[
                    {"id":"all-members", "members":[cell for cell,_ in ledger], "total":total},
                    {"id":"first-two-departments", "members":[cell for cell,_ in ledger[:12]],
                     "total":math.fsum(value for _,value in ledger[:12])}]}
    payload = encode(document)
    approvals = {} if kind == "invalid_approval" else {document["issuer"]:hashlib.sha256(payload).hexdigest()}
    return raw, payload, approvals, {**label,"kind":kind,"errors":retained_errors,
        "decision":"abstain" if kind in {"coupled_ambiguous","coupled_no_solution"} else "repair"}
