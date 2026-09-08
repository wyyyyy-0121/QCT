"""Shared serialization and identity checks for V518 evidence workflows."""

from dataclasses import asdict
from datetime import date

from formulaguard.v5_1_3_development import Candidate, RankedCell, RepairDecision
from formulaguard.v5_1_7_development import JointDiagnosis as V517Diagnosis
from formulaguard.v5_1_7_development import SearchAudit as V517Audit
from formulaguard.v5_1_7_development import Terminal
from formulaguard.v5_1_8_development import JointDiagnosis, SearchAudit
from formulaguard.workbook import WorkbookModel
from scripts.run_v512_evaluation import write_json
from scripts.score_v512_confirmation import sha256

AS_OF = date(2026, 9, 6)


def load_model(raw):
    return WorkbookModel.from_cells({tuple(r[:2]): r[2] for r in raw["cells"]},
                                    {tuple(r[:2]): r[2] for r in raw["formulas"]})


def decode(raw):
    audit = dict(raw["search"])
    current = "numeric_rule" in audit
    audit["terminals"] = tuple(Terminal(tuple(t["prefix"]), t["constraint"]) for t in audit["terminals"])
    cls, audit_cls = (JointDiagnosis, SearchAudit) if current else (V517Diagnosis, V517Audit)
    return cls(raw["backend"], raw["repair_policy"],
               tuple(RankedCell(**{**r, "cell": tuple(r["cell"])}) for r in raw["localization"]),
               tuple(Candidate(**{**r, "cell": tuple(r["cell"])}) for r in raw["candidates"]),
               tuple(RepairDecision(**{**r, "cell": tuple(r["cell"])}) for r in raw["decisions"]), audit_cls(**audit))


def actions(diagnosis):
    return {d.cell: d.accepted_formula for d in diagnosis.decisions if d.accepted_formula is not None}


def check_identity(model, reference, diagnosis):
    if reference.localization != diagnosis.localization or reference.candidates != diagnosis.candidates:
        raise ValueError("localization or candidate portfolio changed")
    results = diagnosis.to_results()
    if [(r.cell, float(r.score).hex()) for r in results] != [(r.cell, float(r.score).hex()) for r in reference.to_results()]:
        raise ValueError("result ranking changed")
    if len(results) != len(model.formulas) or {r.cell for r in results} != set(model.formulas):
        raise ValueError("formula population changed")
    if diagnosis.search.space_size != reference.search.space_size:
        raise ValueError("search domain changed")


def snapshot(root, output, files):
    import shutil
    hashes = {}
    for path in files:
        name = path.relative_to(root).as_posix()
        target = output / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[name] = sha256(path)
    return hashes


def save_diagnosis(path, diagnosis):
    write_json(path, asdict(diagnosis))
