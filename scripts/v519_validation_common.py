"""Serialization and source identity shared by V519 experiment stages."""

from dataclasses import fields
from pathlib import Path

from formulaguard.v5_1_7_development import Terminal
from formulaguard.v5_1_9_development import JointDiagnosis, SearchAudit
from scripts.evaluate_v518_numeric import source_files
from scripts.v518_validation_common import decode as decode_previous
from scripts.v518_validation_common import sha256

ROOT = Path(__file__).resolve().parents[1]


def decode(raw):
    if "proof_version" not in raw["search"]:
        return decode_previous(raw)
    from formulaguard.v5_1_8_development import SearchAudit as PreviousAudit
    old_keys = {f.name for f in fields(PreviousAudit)}
    old = decode_previous({**raw, "search": {k: v for k, v in raw["search"].items() if k in old_keys}})
    audit = dict(raw["search"])
    audit["terminals"] = tuple(Terminal(tuple(t["prefix"]), t["constraint"]) for t in audit["terminals"])
    audit["component_indices"] = tuple(tuple(g) for g in audit["component_indices"])
    audit["radices"] = tuple(audit["radices"])
    audit["preparation_trace"] = tuple(tuple(row) for row in audit["preparation_trace"])
    return JointDiagnosis(old.backend, old.repair_policy, old.localization, old.candidates, old.decisions, SearchAudit(**audit))


def sources():
    files = set(source_files())
    for pattern in ("V519*PLAN.md", "V519*PROTOCOL.md"):
        files.update((ROOT / "research").glob(pattern))
    return {p.relative_to(ROOT).as_posix(): sha256(p) for p in sorted(files)}


def verify_sources(hashes):
    if any(sha256(ROOT / name) != digest for name, digest in hashes.items()):
        raise ValueError("frozen execution source changed")
