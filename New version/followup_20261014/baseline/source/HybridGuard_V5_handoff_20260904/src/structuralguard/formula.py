"""Conservative Excel formula normalization and copy-style translation."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .a1 import Address, format_address, parse_address


REF_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?:(?:'(?:(?:'')|[^'])+'|[A-Za-z_][A-Za-z0-9_. ]*)!)?"
    r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]*"
)
STRING_RE = re.compile(r'"(?:""|[^"])*"')
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.])(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?")
FUNCTION_RE = re.compile(r"(?i)(?<![A-Za-z0-9_.])([A-Z_][A-Z0-9_.]*)\s*\(")
OP_RE = re.compile(r"<=|>=|<>|[+\-*/^&=<>:,()]|")


@dataclass(frozen=True)
class ReferenceInfo:
    sheet: str
    address: str
    row_delta: int | None
    col_delta: int | None
    row_abs: bool
    col_abs: bool


@dataclass(frozen=True)
class FormulaProfile:
    shape: str
    typed_shape: str
    exact_shape: str
    dependency_shape: str
    functions: tuple[str, ...]
    constants: tuple[str, ...]
    references: tuple[ReferenceInfo, ...]
    has_ref_error: bool
    has_direct_self_reference: bool


def _marker_code(index: int) -> str:
    """Letters-only placeholder suffix so numeric normalization cannot alter it."""
    result = ""
    value = index
    while True:
        value, remainder = divmod(value, 26)
        result = chr(65 + remainder) + result
        if value == 0:
            return result
        value -= 1


def _split_sheet_ref(text: str) -> tuple[str | None, str]:
    if "!" not in text:
        return None, text
    sheet, address = text.rsplit("!", 1)
    return sheet, address


def _unquote_sheet(text: str | None, current_sheet: str) -> str:
    if text is None:
        return current_sheet
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    return text


def _protect_strings(formula: str) -> tuple[str, list[str]]:
    strings: list[str] = []

    def replace(match: re.Match[str]) -> str:
        strings.append(match.group())
        return f"§STR{_marker_code(len(strings) - 1)}§"

    return STRING_RE.sub(replace, formula), strings


def _string_class(text: str) -> str:
    value = text[1:-1].replace('""', '"').strip()
    if not value:
        return "STR_EMPTY"
    if value[:2] in {">=", "<=", "<>"} or value[:1] in {">", "<", "="}:
        return "STR_CRITERION"
    if re.fullmatch(r"[A-Za-z]{1,5}", value):
        return "STR_CODE"
    return "STR_TEXT"


def _number_exact(text: str) -> str:
    try:
        value = Decimal(text)
        normalized = value.normalize()
        return format(normalized, "f")
    except InvalidOperation:
        return text.upper()


def _number_class(text: str) -> str:
    try:
        value = float(text)
    except ValueError:
        return "NUM_OTHER"
    if not math.isfinite(value):
        return "NUM_NONFINITE"
    if value == 0:
        return "NUM_ZERO"
    if value == 1:
        return "NUM_ONE"
    if value == -1:
        return "NUM_NEG_ONE"
    if value.is_integer() and abs(value) <= 12:
        return "NUM_SMALL_INT"
    if value.is_integer() and abs(value) in {24, 30, 52, 100, 365}:
        return "NUM_DOMAIN_PERIOD"
    magnitude = int(math.floor(math.log10(abs(value))))
    return f"NUM_{'POS' if value > 0 else 'NEG'}_{'INT' if value.is_integer() else 'DEC'}_E{max(-9, min(9, magnitude)):+d}"


def _sheet_symbol(sheet: str, current_sheet: str) -> str:
    if sheet.casefold() == current_sheet.casefold():
        return "SELF"
    digest = hashlib.blake2s(sheet.casefold().encode("utf-8"), digest_size=3).hexdigest()
    return "OTHER_" + digest


def profile_formula(formula: str, anchor: str, sheet: str) -> FormulaProfile:
    if not isinstance(formula, str) or not formula.startswith("="):
        raise ValueError("formula must start with '='")
    origin = parse_address(anchor)
    protected, strings = _protect_strings(formula.upper())
    refs: list[ReferenceInfo] = []
    ref_symbols: list[str] = []

    def replace_ref(match: re.Match[str]) -> str:
        sheet_text, address_text = _split_sheet_ref(match.group())
        ref_sheet = _unquote_sheet(sheet_text, sheet)
        address = parse_address(address_text)
        row_delta = None if address.row_abs else address.row - origin.row
        col_delta = None if address.col_abs else address.col - origin.col
        refs.append(ReferenceInfo(
            sheet=ref_sheet,
            address=address_text.replace("$", "").upper(),
            row_delta=row_delta,
            col_delta=col_delta,
            row_abs=address.row_abs,
            col_abs=address.col_abs,
        ))
        row_part = f"R{address.row}" if address.row_abs else f"R[{row_delta:+d}]"
        col_part = f"C{address.col}" if address.col_abs else f"C[{col_delta:+d}]"
        symbol = f"{_sheet_symbol(ref_sheet, sheet)}!{row_part}{col_part}"
        ref_symbols.append(symbol)
        return f"§REF{_marker_code(len(ref_symbols) - 1)}§"

    protected = REF_RE.sub(replace_ref, protected)
    number_values = NUMBER_RE.findall(protected)
    shape = NUMBER_RE.sub("NUM", protected)
    typed = NUMBER_RE.sub(lambda m: _number_class(m.group()), protected)
    exact = NUMBER_RE.sub(lambda m: "NUM_" + _number_exact(m.group()), protected)
    for index, symbol in enumerate(ref_symbols):
        marker = f"§REF{_marker_code(index)}§"
        shape = shape.replace(marker, symbol)
        typed = typed.replace(marker, symbol)
        exact = exact.replace(marker, symbol)
    for index, string in enumerate(strings):
        marker = f"§STR{_marker_code(index)}§"
        shape = shape.replace(marker, "STR")
        typed = typed.replace(marker, _string_class(string))
        exact_digest = hashlib.blake2s(string.encode("utf-8"), digest_size=3).hexdigest()
        exact = exact.replace(marker, "STR_" + exact_digest)
    compact = lambda value: re.sub(r"\s+", "", value)
    functions = tuple(match.group(1).upper() for match in FUNCTION_RE.finditer(formula))
    dependency_shape = (
        f"REFS={len(refs)}|CROSS={sum(r.sheet.casefold() != sheet.casefold() for r in refs)}|"
        f"ABS_R={sum(r.row_abs for r in refs)}|ABS_C={sum(r.col_abs for r in refs)}|"
        f"FUNCS={','.join(functions)}"
    )
    direct_self = any(
        ref.sheet.casefold() == sheet.casefold()
        and ref.address.replace("$", "").upper() == anchor.replace("$", "").upper()
        for ref in refs
    )
    return FormulaProfile(
        shape=compact(shape),
        typed_shape=compact(typed),
        exact_shape=compact(exact),
        dependency_shape=dependency_shape,
        functions=functions,
        constants=tuple(_number_exact(value) for value in number_values),
        references=tuple(refs),
        has_ref_error="#REF!" in formula.upper(),
        has_direct_self_reference=direct_self,
    )


def translate_formula(formula: str, source_anchor: str, target_anchor: str) -> str:
    source = parse_address(source_anchor)
    target = parse_address(target_anchor)
    dr, dc = target.row - source.row, target.col - source.col
    protected, strings = _protect_strings(formula)

    def replace(match: re.Match[str]) -> str:
        sheet_text, ref_text = _split_sheet_ref(match.group())
        ref = parse_address(ref_text)
        row = ref.row if ref.row_abs else ref.row + dr
        col = ref.col if ref.col_abs else ref.col + dc
        if row < 1 or col < 1:
            return "#REF!"
        prefix = f"{sheet_text}!" if sheet_text is not None else ""
        return prefix + format_address(Address(row, col, ref.row_abs, ref.col_abs))

    translated = REF_RE.sub(replace, protected)
    for index, string in enumerate(strings):
        translated = translated.replace(f"§STR{_marker_code(index)}§", string)
    return translated
