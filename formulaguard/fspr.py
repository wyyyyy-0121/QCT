"""Formula-pair defect prior and bounded V4 fifth-slot reranking."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from .a1 import num_to_col
from .formula import Binary, Func, Node, Number, Range, Ref, Unary, parse_formula
from .localize import LocalizationResult, v4_scores
from .workbook import WorkbookModel

PROTOCOL = "formulaguard_fspr_v1"
MODEL_VERSION = "v5-fspr1-candidate"
ARCHITECTURE = "frozen_v4_top4_plus_high_confidence_fspr_fifth"
DIMENSIONS = 2048
V4_PREFIX = 4
REVIEW_BUDGET = 5
TOKENIZER_VERSION = "fspr-anchor-independent-v1"
_STRING_RE = re.compile(r'"(?:[^"]|"")*"')
_REF_RE = re.compile(
    r"(?:(?:'(?:(?:'')|[^'])+'|[A-Za-z_][A-Za-z0-9_.]*)!)?"
    r"\$?[A-Za-z]{1,3}\$?[1-9]\d*"
)
_NUMBER_RE = re.compile(r"(?<![A-Za-z_])(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?")
_LEX_RE = re.compile(r"[A-Z_][A-Z0-9_.]*|<=|>=|<>|[+\-*/^=<>:,()]|STR|REF|NUM")
_IDENTIFIER_RE = re.compile(r"[A-Z_][A-Z0-9_.]*")
_LEXICAL_PLACEHOLDERS = {"STR", "REF", "NUM"}
_CELL_REF_RE = re.compile(
    r"^(?:(?P<sheet>'(?:(?:'')|[^'])+'|[A-Za-z_][A-Za-z0-9_.]*)!)?"
    r"(?P<address>\$?[A-Za-z]{1,3}\$?[1-9]\d*)$"
)

ValueLookup = Callable[[str | None, str], str]


def _count_bucket(value: int) -> str:
    if value == 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 3:
        return "2_3"
    if value <= 7:
        return "4_7"
    if value <= 15:
        return "8_15"
    return "16_PLUS"


def _span_bucket(value: int) -> str:
    if value == 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 4:
        return "2_4"
    if value <= 16:
        return "5_16"
    return "17_PLUS"


def _length_bucket(value: int) -> str:
    if value <= 8:
        return "0_8"
    if value <= 16:
        return "9_16"
    if value <= 32:
        return "17_32"
    if value <= 64:
        return "33_64"
    return "65_PLUS"


def _number_category(value: float) -> str:
    if not math.isfinite(value):
        return "NONFINITE"
    if value == 0:
        return "ZERO"
    if value == 1:
        return "ONE"
    if value == -1:
        return "NEG_ONE"
    prefix = "NEG_" if value < 0 else ""
    magnitude = abs(value)
    if not magnitude.is_integer():
        return prefix + "FRACTION"
    if magnitude < 10:
        return prefix + "INTEGER_2_9"
    if magnitude < 100:
        return prefix + "INTEGER_10_99"
    return prefix + "INTEGER_100_PLUS"


def _ref_tokens(ref: Ref) -> list[str]:
    address = ref.address
    return [
        "REF",
        "SHEET_EXPLICIT" if ref.sheet is not None else "SHEET_LOCAL",
        "ROW_ABSOLUTE" if address.row_abs else "ROW_RELATIVE",
        "COL_ABSOLUTE" if address.col_abs else "COL_RELATIVE",
    ]


def _ast_tokens(node: Node) -> tuple[list[str], list[Ref | Range], int]:
    if isinstance(node, Number):
        return ["NUMBER", "NUMBER_" + _number_category(node.value)], [], 1
    if isinstance(node, Ref):
        return _ref_tokens(node), [node], 1
    if isinstance(node, Range):
        row_span = abs(node.end.address.row - node.start.address.row)
        col_span = abs(node.end.address.col - node.start.address.col)
        return (
            [
                "RANGE",
                *_ref_tokens(node.start),
                *_ref_tokens(node.end),
                "RANGE_ROW_SPAN_" + _span_bucket(row_span),
                "RANGE_COL_SPAN_" + _span_bucket(col_span),
            ],
            [node],
            1,
        )
    if isinstance(node, Unary):
        child, refs, depth = _ast_tokens(node.value)  # type: ignore[arg-type]
        return ["UNARY", "OP_" + node.op, *child, "UNARY_END"], refs, depth + 1
    if isinstance(node, Binary):
        left, left_refs, left_depth = _ast_tokens(node.left)  # type: ignore[arg-type]
        right, right_refs, right_depth = _ast_tokens(node.right)  # type: ignore[arg-type]
        return (
            ["BINARY", "OP_" + node.op, "LEFT", *left, "RIGHT", *right, "BINARY_END"],
            [*left_refs, *right_refs],
            max(left_depth, right_depth) + 1,
        )
    if isinstance(node, Func):
        tokens = ["FUNCTION", "FUNC_" + node.name, "ARITY_" + _count_bucket(len(node.args))]
        refs: list[Ref | Range] = []
        depths = [0]
        for index, argument in enumerate(node.args):
            child, child_refs, depth = _ast_tokens(argument)  # type: ignore[arg-type]
            tokens.extend(("ARG_" + str(min(index, 7)), *child))
            refs.extend(child_refs)
            depths.append(depth)
        tokens.append("FUNCTION_END")
        return tokens, refs, max(depths) + 1
    raise TypeError(type(node))


def _lexical_tokens(formula: str) -> list[str]:
    text = _STRING_RE.sub(" STR ", formula.upper())
    text = _REF_RE.sub(" REF ", text)
    text = _NUMBER_RE.sub(" NUM ", text)
    tokens = []
    for match in _LEX_RE.finditer(text):
        token = match.group()
        if _IDENTIFIER_RE.fullmatch(token) and token not in _LEXICAL_PLACEHOLDERS:
            suffix = text[match.end() :].lstrip()
            token = "FUNC_" + token if suffix.startswith("(") else "IDENT"
        tokens.append("LEX_" + token[:48])
    return tokens


def _reference_value_kinds(
    references: Sequence[Ref | Range],
    lookup: ValueLookup | None,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    if lookup is None:
        return counts
    for reference in references:
        if isinstance(reference, Ref):
            counts[lookup(reference.sheet, reference.address.a1)] += 1
            continue
        start, end = reference.start.address, reference.end.address
        cells = (abs(end.row - start.row) + 1) * (abs(end.col - start.col) + 1)
        if cells > 64:
            counts["sample_capped"] += 1
            endpoints = (reference.start, reference.end)
            for endpoint in endpoints:
                counts[lookup(endpoint.sheet, endpoint.address.a1)] += 1
            continue
        row_start, row_end = sorted((start.row, end.row))
        col_start, col_end = sorted((start.col, end.col))
        sheet = reference.start.sheet or reference.end.sheet
        for row in range(row_start, row_end + 1):
            for col in range(col_start, col_end + 1):
                counts[lookup(sheet, f"{num_to_col(col)}{row}")] += 1
    return counts


def formula_feature_tokens(
    formula: str,
    *,
    value_lookup: ValueLookup | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return address-free syntax and referenced-value context tokens."""

    lexical = _lexical_tokens(formula)
    references: list[Ref | Range] = []
    try:
        ast, references, depth = _ast_tokens(parse_formula(formula))
        syntax = ["SYN_AST_SUPPORTED", *ast]
    except (TypeError, ValueError):
        depth = 0
        syntax = ["SYN_UNSUPPORTED_AST", *lexical]
    syntax.extend(
        (
            "SYN_LENGTH_" + _length_bucket(len(formula)),
            "SYN_DEPTH_" + _count_bucket(depth),
            "SYN_LEX_COUNT_" + _count_bucket(len(lexical)),
            "SYN_REF_NODE_COUNT_" + _count_bucket(len(references)),
        )
    )
    kinds = _reference_value_kinds(references, value_lookup)
    context = [
        "CTX_" + kind.upper() + "_COUNT_" + _count_bucket(count)
        for kind, count in sorted(kinds.items())
    ]
    context.append("CTX_REFERENCE_TYPES_" + _count_bucket(len(kinds)))
    return tuple(syntax), tuple(context)


def _hash_token(token: str, dimensions: int) -> tuple[int, float]:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "big") % dimensions
    sign = 1.0 if digest[8] & 1 else -1.0
    return index, sign


def hashed_features(
    syntax_tokens: Sequence[str],
    context_tokens: Sequence[str],
    *,
    view: str = "full",
    dimensions: int = DIMENSIONS,
) -> dict[int, float]:
    """Create the frozen signed unigram/bigram sparse feature vector."""

    if dimensions < 1:
        raise ValueError("feature dimensions must be positive")
    if view == "full":
        streams = (("S", syntax_tokens), ("C", context_tokens))
    elif view == "syntax_only":
        streams = (("S", syntax_tokens),)
    elif view == "context_only":
        streams = (("C", context_tokens),)
    else:
        raise ValueError(f"unknown FSPR feature view: {view}")
    values: Counter[int] = Counter()
    for prefix, stream in streams:
        names = [f"{prefix}:U:{token}" for token in stream]
        names.extend(
            f"{prefix}:B:{left}>{right}"
            for left, right in pairwise(stream)
        )
        for name in names:
            index, sign = _hash_token(name, dimensions)
            values[index] += sign
    norm = math.sqrt(sum(value * value for value in values.values()))
    if norm == 0:
        return {}
    return {index: value / norm for index, value in sorted(values.items()) if value}


def workbook_value_lookup(model: WorkbookModel, current_sheet: str) -> ValueLookup:
    def lookup(sheet: str | None, address: str) -> str:
        key = (sheet or current_sheet, address.replace("$", ""))
        if key in model.formulas:
            return "formula"
        if key not in model.cells or model.cells[key] in (None, ""):
            return "blank"
        value = model.cells[key]
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "numeric"
        if isinstance(value, str) and value.startswith("#"):
            return "error"
        return "text"

    return lookup


def forepbench_value_lookup(data: Mapping[str, object]) -> ValueLookup:
    sheets = data.get("sheets")
    sheet_names = data.get("sheetNames")
    if not isinstance(sheets, Mapping) or not isinstance(sheet_names, list) or not sheet_names:
        raise ValueError("FoRepBench context has no usable sheet mapping")
    default_sheet = str(sheet_names[0])

    def lookup(sheet: str | None, address: str) -> str:
        raw_sheet = sheets.get(sheet or default_sheet)
        if not isinstance(raw_sheet, Mapping):
            return "missing"
        cells = raw_sheet.get("cells")
        if not isinstance(cells, Mapping):
            return "missing"
        raw_cell = cells.get(address.replace("$", ""))
        if not isinstance(raw_cell, Mapping):
            return "blank"
        if "f" in raw_cell:
            return "formula"
        value_type = str(raw_cell.get("t", ""))
        value = raw_cell.get("v")
        if value in (None, ""):
            return "blank"
        if value_type == "n":
            return "numeric"
        if value_type == "b":
            return "boolean"
        if value_type == "e" or (isinstance(value, str) and value.startswith("#")):
            return "error"
        return "text"

    return lookup


@dataclass(frozen=True)
class FSPRModel:
    weights: tuple[float, ...]
    intercept: float
    threshold: float
    selected_c: float
    model_sha256: str

    def decision_value(
        self,
        syntax_tokens: Sequence[str],
        context_tokens: Sequence[str],
        *,
        view: str = "full",
    ) -> float:
        features = hashed_features(syntax_tokens, context_tokens, view=view)
        return self.intercept + sum(self.weights[index] * value for index, value in features.items())


def load_model(path: str | Path) -> FSPRModel:
    path = Path(path)
    raw = path.read_bytes()
    payload = json.loads(raw)
    weights = payload.get("weights")
    if (
        payload.get("protocol") != PROTOCOL
        or payload.get("tokenizer_version") != TOKENIZER_VERSION
        or payload.get("dimensions") != DIMENSIONS
        or not isinstance(weights, list)
        or len(weights) != DIMENSIONS
    ):
        raise ValueError("invalid FSPR model artifact")
    return FSPRModel(
        weights=tuple(float(value) for value in weights),
        intercept=float(payload["intercept"]),
        threshold=float(payload["threshold"]),
        selected_c=float(payload["selected_c"]),
        model_sha256=hashlib.sha256(raw).hexdigest(),
    )


@dataclass(frozen=True)
class FSPRDecision:
    ranking: tuple[str, ...]
    fspr_candidate: str | None
    displaced_v4_fifth: str | None
    candidate_logit: float | None
    changed: bool


def fspr_decision(
    v4_ranking: Sequence[str],
    logits: Mapping[str, float],
    threshold: float,
) -> FSPRDecision:
    """Apply the frozen high-confidence fifth-slot rule."""

    v4 = tuple(str(cell) for cell in v4_ranking)
    if len(set(v4)) != len(v4):
        raise ValueError("V4 ranking contains duplicate cells")
    if len(v4) <= V4_PREFIX:
        return FSPRDecision(v4, None, None, None, False)
    unknown = set(logits) - set(v4)
    if unknown:
        raise ValueError("FSPR logits contain cells outside the V4 inventory")
    rank = {cell: index for index, cell in enumerate(v4)}
    eligible = [cell for cell in v4[V4_PREFIX:] if cell in logits]
    if not eligible:
        return FSPRDecision(v4, None, None, None, False)
    candidate = min(eligible, key=lambda cell: (-float(logits[cell]), rank[cell]))
    candidate_logit = float(logits[candidate])
    if candidate_logit < threshold or candidate == v4[V4_PREFIX]:
        return FSPRDecision(v4, candidate, None, candidate_logit, False)
    reordered = (
        *v4[:V4_PREFIX],
        candidate,
        *(cell for cell in v4[V4_PREFIX:] if cell != candidate),
    )
    if len(reordered) != len(v4) or set(reordered) != set(v4):
        raise AssertionError("FSPR reranking changed the formula inventory")
    return FSPRDecision(
        tuple(reordered),
        candidate,
        v4[V4_PREFIX],
        candidate_logit,
        True,
    )


def workbook_logits(model: WorkbookModel, classifier: FSPRModel) -> dict[str, float]:
    logits: dict[str, float] = {}
    for key in model.formula_cells:
        if not model.is_visible(key) or model.formula_kind(key) not in {"normal", "shared"}:
            continue
        syntax, context = formula_feature_tokens(
            model.formulas[key],
            value_lookup=workbook_value_lookup(model, key[0]),
        )
        logits[f"{key[0]}!{key[1]}"] = classifier.decision_value(syntax, context)
    return logits


def v4_fspr_scores(
    model: WorkbookModel,
    model_path: str | Path,
    *,
    candidate_limit: int = 15,
) -> list[LocalizationResult]:
    """Return the complete frozen V4-plus-FSPR candidate ranking."""

    classifier = load_model(model_path)
    v4 = v4_scores(model, candidate_limit=candidate_limit)
    decision = fspr_decision(
        [row.cell_label for row in v4],
        workbook_logits(model, classifier),
        classifier.threshold,
    )
    by_cell = {row.cell_label: row for row in v4}
    v4_rank = {row.cell_label: index for index, row in enumerate(v4, 1)}
    total = len(decision.ranking)
    results: list[LocalizationResult] = []
    for rank, label in enumerate(decision.ranking, 1):
        base = by_cell[label]
        evidence = dict(base.evidence)
        evidence.update(
            {
                "model_version": MODEL_VERSION,
                "architecture": ARCHITECTURE,
                "review_budget": REVIEW_BUDGET,
                "immutable_v4_prefix": V4_PREFIX,
                "original_v4_rank": v4_rank[label],
                "fspr_model_sha256": classifier.model_sha256,
                "fspr_threshold": classifier.threshold,
                "selected_fspr_fifth": int(
                    decision.changed and label == decision.fspr_candidate and rank == REVIEW_BUDGET
                ),
                "ranking_changed": int(decision.changed),
            }
        )
        results.append(
            LocalizationResult(
                cell=base.cell,
                score=(total - rank + 1) / total if total else 0.0,
                candidate_formula=base.candidate_formula,
                evidence=evidence,
            )
        )
    return results


__all__ = [
    "ARCHITECTURE",
    "DIMENSIONS",
    "MODEL_VERSION",
    "PROTOCOL",
    "REVIEW_BUDGET",
    "TOKENIZER_VERSION",
    "V4_PREFIX",
    "FSPRDecision",
    "FSPRModel",
    "forepbench_value_lookup",
    "formula_feature_tokens",
    "fspr_decision",
    "hashed_features",
    "load_model",
    "v4_fspr_scores",
    "workbook_logits",
    "workbook_value_lookup",
]
