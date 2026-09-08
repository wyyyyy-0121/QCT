"""True dependency fixtures derived from explicit business arithmetic, not inference."""

import hashlib
import math

from scripts.build_v515_constraint_cases import binding, encode, intended
from scripts.build_v518_numeric_cases import build_case

FAMILIES = ("product", "ratio", "weighted")
STRUCTURES = ("pair", "chain", "fan_in", "shared_bridge")
SEEDS = ("v519-g1-0", "v519-g1-1")


def build_component_case(count, family="product", structure="pair", seed=SEEDS[0]):
    if count < 4 or family not in FAMILIES or structure not in STRUCTURES:
        raise ValueError("invalid component fixture")
    raw, _, _, label = build_case(count, family, "unique", seed)
    first = [next(r for r in raw["formulas"] if r[0] == f"Dept_{i:03d}") for i in range(count)]
    links = {1: (0,)} if structure == "pair" else {1: (0,), 2: (1,)} if structure == "chain" else {2: (0, 1)}
    if structure == "shared_bridge":
        links = {2: (0, 1), 3: (0, 1)}
    values = {tuple(r[:2]): r[2] for r in raw["cells"]}
    healthy_first, ledger = {}, []
    for i, (sheet, address, _) in enumerate(first):
        row = int(address[1:])
        target = (sheet, f"B{row}")
        b = values[target]
        if i in links:
            refs = [f"'{first[j][0]}'!{first[j][1]}" for j in links[i]]
            upstream = healthy_first[links[i][0]]
            if len(links[i]) == 2:
                upstream += healthy_first[links[i][1]]
            expression = "+".join(refs)
            if structure == "shared_bridge":
                expression = "'Bridge'!A1"
            raw["cells"] = [r for r in raw["cells"] if tuple(r[:2]) != target]
            raw["formulas"].append([*target, f"={b}+0.125*({expression})"])
            b += 0.125 * upstream
        healthy_first[i] = intended(family, row, b, values[(sheet, f"C{row}")], values[(sheet, f"D{row}")])[1]
        for offset in range(6):
            r = row + offset
            value = intended(family, r, b if offset == 0 else values[(sheet, f"B{r}")],
                             values[(sheet, f"C{r}")], values[(sheet, f"D{r}")])[1]
            ledger.append(([sheet, f"H{r}"], value))
    if structure == "shared_bridge":
        raw["formulas"].append(["Bridge", "A1", f"='{first[0][0]}'!{first[0][1]}+'{first[1][0]}'!{first[1][1]}"])
        ledger.append((["Bridge", "A1"], healthy_first[0] + healthy_first[1]))
    document = {"issuer": "simulated-component-ledger", "workbook_binding": binding(raw),
                "valid_from": "2026-09-01", "valid_until": "2026-09-30", "aggregates": [
                    {"id": "all-members", "members": [c for c, _ in ledger], "total": math.fsum(v for _, v in ledger)},
                    {"id": "first-two-departments", "members": [c for c, _ in ledger[:12]],
                     "total": math.fsum(v for _, v in ledger[:12])}]}
    payload = encode(document)
    return raw, payload, {document["issuer"]: hashlib.sha256(payload).hexdigest()}, {**label, "structure": structure}
