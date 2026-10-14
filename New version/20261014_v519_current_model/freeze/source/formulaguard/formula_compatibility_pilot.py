"""Deterministic token corruptions for formula-compatibility development."""

from __future__ import annotations

from collections.abc import Sequence

PROTOCOL = "formulaguard_formula_compatibility_pilot_v1"
OPERATOR_REPLACEMENTS = {
    "OP_+": "OP_-",
    "OP_-": "OP_+",
    "OP_*": "OP_/",
    "OP_/": "OP_*",
    "OP_^": "OP_*",
    "OP_>": "OP_>=",
    "OP_>=": "OP_>",
    "OP_<": "OP_<=",
    "OP_<=": "OP_<",
    "OP_=": "OP_>",
}
FUNCTION_REPLACEMENTS = {
    "FUNC_SUM": "FUNC_AVERAGE",
    "FUNC_AVERAGE": "FUNC_SUM",
    "FUNC_MIN": "FUNC_MAX",
    "FUNC_MAX": "FUNC_MIN",
    "FUNC_COUNT": "FUNC_COUNTA",
    "FUNC_COUNTA": "FUNC_COUNT",
    "FUNC_ROUND": "FUNC_ROUNDUP",
    "FUNC_ROUNDUP": "FUNC_ROUND",
}
NUMERIC_REPLACEMENTS = {
    "NUM_ZERO": "NUM_ONE",
    "NUM_ONE": "NUM_ZERO",
    "NUM_NEG_ONE": "NUM_ONE",
    "NUM_FRACTION": "NUM_INTEGER_2_9",
    "NUM_NEG_FRACTION": "NUM_FRACTION",
    "NUM_INTEGER_2_9": "NUM_INTEGER_10_99",
    "NUM_NEG_INTEGER_2_9": "NUM_INTEGER_2_9",
    "NUM_INTEGER_10_99": "NUM_INTEGER_100_PLUS",
    "NUM_NEG_INTEGER_10_99": "NUM_INTEGER_10_99",
    "NUM_INTEGER_100_PLUS": "NUM_INTEGER_10_99",
    "NUM_NEG_INTEGER_100_PLUS": "NUM_INTEGER_100_PLUS",
}


def _replace_first(tokens: Sequence[str], replacements: dict[str, str]) -> tuple[str, ...] | None:
    for index, token in enumerate(tokens):
        replacement = replacements.get(token)
        if replacement is None:
            continue
        result = list(tokens)
        result[index] = replacement
        return tuple(result)
    return None


def _reference_offset_mutation(tokens: Sequence[str]) -> tuple[str, ...] | None:
    for index, token in enumerate(tokens):
        if token == "OFFSET_POS":
            result = list(tokens)
            result[index] = "OFFSET_NEG"
            return tuple(result)
        if token == "OFFSET_NEG":
            result = list(tokens)
            result[index] = "OFFSET_POS"
            return tuple(result)
        if token == "OFFSET_ZERO":
            result = list(tokens)
            result[index] = "OFFSET_POS"
            if index + 1 < len(result) and result[index + 1] == "DIGIT_0":
                result[index + 1] = "DIGIT_1"
            return tuple(result)
    return None


def _anchor_mutation(tokens: Sequence[str]) -> tuple[str, ...] | None:
    replacements = {
        "ROW_REL": "ROW_ABS",
        "ROW_ABS": "ROW_REL",
        "COL_REL": "COL_ABS",
        "COL_ABS": "COL_REL",
    }
    return _replace_first(tokens, replacements)


def _sheet_relation_mutation(tokens: Sequence[str]) -> tuple[str, ...] | None:
    return _replace_first(tokens, {"SELF": "OTHER", "OTHER": "SELF"})


def token_mutations(
    tokens: Sequence[str],
    *,
    maximum: int = 5,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return bounded structural corruptions in the fixed pilot order."""

    if maximum < 1:
        raise ValueError("formula mutation limit must be positive")
    operations = (
        ("operator", _replace_first(tokens, OPERATOR_REPLACEMENTS)),
        ("function", _replace_first(tokens, FUNCTION_REPLACEMENTS)),
        ("reference_offset", _reference_offset_mutation(tokens)),
        ("anchor", _anchor_mutation(tokens)),
        ("numeric", _replace_first(tokens, NUMERIC_REPLACEMENTS)),
        ("sheet_relation", _sheet_relation_mutation(tokens)),
    )
    observed = tuple(tokens)
    seen = {observed}
    result = []
    for kind, candidate in operations:
        if candidate is None or candidate in seen:
            continue
        seen.add(candidate)
        result.append((kind, candidate))
        if len(result) == maximum:
            break
    return tuple(result)


def candidate_rows(example: dict[str, object], *, maximum_mutations: int = 5) -> list[dict[str, object]]:
    observed = tuple(str(token) for token in example["observed_tokens"])  # type: ignore[union-attr]
    rows = [{"kind": "observed", "tokens": observed}]
    seen = {observed}
    for kind, tokens in token_mutations(observed, maximum=maximum_mutations):
        seen.add(tokens)
        rows.append({"kind": kind, "tokens": tokens})
    repairs = example.get("repair_candidates", [])
    if not isinstance(repairs, list):
        raise ValueError("formula compatibility repair candidates are malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    for repair in repairs:
        if not isinstance(repair, dict) or not isinstance(repair.get("tokens"), list):
            raise ValueError("formula compatibility repair candidate is malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
        tokens = tuple(str(token) for token in repair["tokens"])
        if tokens in seen:
            continue
        seen.add(tokens)
        rows.append({"kind": "peer", "tokens": tokens})
    return rows


__all__ = [
    "FUNCTION_REPLACEMENTS",
    "NUMERIC_REPLACEMENTS",
    "OPERATOR_REPLACEMENTS",
    "PROTOCOL",
    "candidate_rows",
    "token_mutations",
]
