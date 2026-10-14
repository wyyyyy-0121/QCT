"""Target-label-free semantic compatibility primitives for formula ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .a1 import parse_address
from .cwrp import formula_role_fingerprint
from .formula import REF_RE, translate_formula
from .workbook import CellKey, WorkbookModel


MODEL_VERSION = "semantic-formula-compatibility-pilot-v2"
ROLE_PROTOCOL = "formulaguard_semantic_formula_role_v2"
SPECIAL_TOKENS = ("<PAD>", "<UNK>", "<START>", "<END>")
TOKEN_RE = re.compile(
    r"(?:SELF|OTHER)!R(?:\[-?\+?\d+\]|\d+)C(?:\[-?\+?\d+\]|\d+)"
    r"|[A-Z_][A-Z0-9_.]*|<=|>=|<>|[+\-*/^=<>:,()]|NUM|STR"
)
NUMBER_RE = re.compile(r"(?<![A-Z0-9_.])(?:\d+(?:\.\d*)?|\.\d+)(?:E[+\-]?\d+)?", re.I)
STRING_RE = re.compile(r'"(?:[^"]|"")*"')
ROLE_REFERENCE_RE = re.compile(
    r"^(SELF|OTHER)!R(\[-?\+?\d+\]|\d+)C(\[-?\+?\d+\]|\d+)$"
)


def _fallback_reference(match: re.Match[str], anchor_text: str, current_sheet: str) -> str:
    text = match.group()
    if "!" in text:
        sheet_text, address_text = text.rsplit("!", 1)
        sheet = sheet_text.strip("'").replace("''", "'")
        relation = "SELF" if sheet.casefold() == current_sheet.casefold() else "OTHER"
    else:
        address_text = text
        relation = "SELF"
    address = parse_address(address_text)
    anchor = parse_address(anchor_text)
    row = f"R{address.row}" if address.row_abs else f"R[{address.row - anchor.row:+d}]"
    col = f"C{address.col}" if address.col_abs else f"C[{address.col - anchor.col:+d}]"
    return f"{relation}!{row}{col}"


def canonical_formula_role(formula: str, anchor_text: str, current_sheet: str) -> str:
    """Return a literal- and sheet-name-bounded role for any formula string."""

    try:
        return formula_role_fingerprint(formula, anchor_text, current_sheet)
    except (TypeError, ValueError):
        body = formula[1:] if formula.startswith("=") else formula
        body = STRING_RE.sub("STR", body)
        references: list[str] = []

        def replace_reference(match: re.Match[str]) -> str:
            references.append(_fallback_reference(match, anchor_text, current_sheet))
            return f"__REF{len(references) - 1}__"

        body = REF_RE.sub(replace_reference, body)
        body = NUMBER_RE.sub("NUM", body)
        for index, reference in enumerate(references):
            body = body.replace(f"__REF{index}__", reference)
        return "LEX(" + re.sub(r"\s+", "", body).upper() + ")"


def role_tokens(role: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for token in TOKEN_RE.findall(role.upper()):
        reference = ROLE_REFERENCE_RE.fullmatch(token)
        if reference is None:
            tokens.append(token)
            continue
        tokens.append("REF_" + reference.group(1))
        for axis, coordinate in (("ROW", reference.group(2)), ("COL", reference.group(3))):
            relative = coordinate.startswith("[")
            tokens.append(f"{axis}_{'REL' if relative else 'ABS'}")
            value = int(coordinate.strip("[]"))
            if relative:
                tokens.append(
                    "DELTA_ZERO" if value == 0 else "DELTA_POS" if value > 0 else "DELTA_NEG"
                )
            tokens.extend(f"DIGIT_{digit}" for digit in str(abs(value)))
    return tuple(tokens) or ("<UNK>",)


@dataclass(frozen=True)
class FormulaVocabulary:
    tokens: tuple[str, ...]

    @classmethod
    def build(
        cls,
        roles: Iterable[str],
        *,
        minimum_count: int = 2,
        maximum_size: int = 16384,
    ) -> "FormulaVocabulary":
        if minimum_count < 1 or maximum_size < len(SPECIAL_TOKENS):
            raise ValueError("invalid formula vocabulary bounds")
        counts: dict[str, int] = {}
        for role in roles:
            for token in role_tokens(role):
                counts[token] = counts.get(token, 0) + 1
        selected = sorted(
            (token for token, count in counts.items() if count >= minimum_count),
            key=lambda token: (-counts[token], token),
        )[: maximum_size - len(SPECIAL_TOKENS)]
        return cls((*SPECIAL_TOKENS, *selected))

    @property
    def token_to_id(self) -> Mapping[str, int]:
        return {token: index for index, token in enumerate(self.tokens)}

    def encode(self, role: str, *, maximum_length: int = 96) -> tuple[int, ...]:
        if maximum_length < 2:
            raise ValueError("maximum formula length must retain boundary tokens")
        ids = self.token_to_id
        body = [ids.get(token, ids["<UNK>"]) for token in role_tokens(role)]
        body = body[: maximum_length - 2]
        return (ids["<START>"], *body, ids["<END>"])


def pad_token_ids(
    rows: Sequence[Sequence[int]],
    *,
    padding_id: int = 0,
) -> tuple[list[list[int]], list[int]]:
    if not rows:
        raise ValueError("cannot pad an empty formula batch")
    lengths = [len(row) for row in rows]
    if min(lengths) < 1:
        raise ValueError("formula token sequence is empty")
    width = max(lengths)
    return [list(row) + [padding_id] * (width - len(row)) for row in rows], lengths


def semantic_candidate_roles(
    model: WorkbookModel,
    target: CellKey,
    *,
    limit: int = 4,
) -> tuple[str, ...]:
    """Return deterministic local hard negatives without reading fault labels."""

    if limit < 1:
        raise ValueError("semantic candidate limit must be positive")
    if target not in model.formulas:
        raise ValueError("semantic target is not a formula")
    sheet, address_text = target
    address = parse_address(address_text)
    observed = canonical_formula_role(model.formulas[target], address_text, sheet)
    records: list[tuple[int, int, str]] = []
    for peer, formula in model.formulas.items():
        if peer == target or peer[0] != sheet or not model.is_visible(peer):
            continue
        peer_address = parse_address(peer[1])
        distance = abs(peer_address.row - address.row) + abs(peer_address.col - address.col)
        same_axis = peer_address.row == address.row or peer_address.col == address.col
        if same_axis:
            translated = translate_formula(formula, peer[1], address_text)
            role = canonical_formula_role(translated, address_text, sheet)
            priority = 0
        else:
            role = canonical_formula_role(formula, peer[1], sheet)
            priority = 1
        if role != observed:
            records.append((priority, distance, role))
    result: list[str] = []
    for _priority, _distance, role in sorted(records):
        if role not in result:
            result.append(role)
            if len(result) == limit:
                break
    return tuple(result)


__all__ = [
    "FormulaVocabulary",
    "MODEL_VERSION",
    "ROLE_PROTOCOL",
    "SPECIAL_TOKENS",
    "canonical_formula_role",
    "pad_token_ids",
    "role_tokens",
    "semantic_candidate_roles",
]
