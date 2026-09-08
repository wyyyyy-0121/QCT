"""Small, auditable Excel-formula parser for the supported research subset."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .a1 import Address, parse_address

REF_PATTERN = r"(?:(?:'(?:(?:'')|[^'])+'|[A-Za-z_][A-Za-z0-9_.]*)!)?\$?[A-Za-z]{1,3}\$?[1-9]\d*"
TOKEN_RE = re.compile(
    rf"(?P<WS>\s+)|(?P<REF>{REF_PATTERN})|(?P<NUMBER>(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)|"
    r"(?P<OP><=|>=|<>|[+\-*/^=<>:,()])|(?P<IDENT>[A-Za-z_][A-Za-z0-9_.]*)"
)
REF_RE = re.compile(REF_PATTERN)


class FormulaSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class Number:
    value: float
    source_text: str | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Ref:
    address: Address
    sheet: str | None = None


@dataclass(frozen=True)
class Range:
    start: Ref
    end: Ref


@dataclass(frozen=True)
class Unary:
    op: str
    value: object


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Func:
    name: str
    args: tuple[object, ...]


Node = Number | Ref | Range | Unary | Binary | Func


def tokenize(formula: str) -> list[Token]:
    text = formula.removeprefix("=")
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        match = TOKEN_RE.match(text, pos)
        if not match:
            raise FormulaSyntaxError(f"Unsupported token at column {pos + 1}: {text[pos:pos+20]!r}")
        kind = match.lastgroup or ""
        if kind != "WS":
            tokens.append(Token(kind, match.group(), match.start(), match.end()))
        pos = match.end()
    tokens.append(Token("EOF", "", len(text), len(text)))
    return tokens


def _parse_ref(text: str) -> Ref:
    if "!" in text:
        sheet_text, cell_text = text.rsplit("!", 1)
        if sheet_text.startswith("'") and sheet_text.endswith("'"):
            sheet = sheet_text[1:-1].replace("''", "'")
        else:
            sheet = sheet_text
    else:
        sheet = None
        cell_text = text
    return Ref(parse_address(cell_text), sheet)


class Parser:
    def __init__(self, formula: str):
        self.formula = formula
        self.tokens = tokenize(formula)
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def accept(self, value: str) -> bool:
        if self.current.value.upper() == value.upper():
            self.index += 1
            return True
        return False

    def expect(self, value: str) -> None:
        if not self.accept(value):
            raise FormulaSyntaxError(f"Expected {value!r}, found {self.current.value!r} in {self.formula!r}")

    def parse(self) -> Node:
        node = self.comparison()
        if self.current.kind != "EOF":
            raise FormulaSyntaxError(f"Unexpected token {self.current.value!r} in {self.formula!r}")
        return node

    def comparison(self) -> Node:
        node = self.addition()
        while self.current.value in ("=", "<>", "<", ">", "<=", ">="):
            op = self.current.value
            self.index += 1
            node = Binary(op, node, self.addition())
        return node

    def addition(self) -> Node:
        node = self.multiplication()
        while self.current.value in ("+", "-"):
            op = self.current.value
            self.index += 1
            node = Binary(op, node, self.multiplication())
        return node

    def multiplication(self) -> Node:
        node = self.power()
        while self.current.value in ("*", "/"):
            op = self.current.value
            self.index += 1
            node = Binary(op, node, self.power())
        return node

    def power(self) -> Node:
        node = self.unary()
        if self.accept("^"):
            node = Binary("^", node, self.power())
        return node

    def unary(self) -> Node:
        if self.accept("+"):
            return Unary("+", self.unary())
        if self.accept("-"):
            return Unary("-", self.unary())
        return self.primary()

    def primary(self) -> Node:
        token = self.current
        if token.kind == "NUMBER":
            self.index += 1
            return Number(float(token.value), source_text=token.value)
        if token.kind == "REF":
            self.index += 1
            left = _parse_ref(token.value)
            if self.accept(":"):
                if self.current.kind != "REF":
                    raise FormulaSyntaxError("Range endpoint must be a cell reference")
                right = _parse_ref(self.current.value)
                self.index += 1
                return Range(left, right)
            return left
        if token.kind == "IDENT":
            name = token.value.upper()
            self.index += 1
            self.expect("(")
            args: list[Node] = []
            if not self.accept(")"):
                while True:
                    args.append(self.comparison())
                    if self.accept(")"):
                        break
                    self.expect(",")
            return Func(name, tuple(args))
        if self.accept("("):
            node = self.comparison()
            self.expect(")")
            return node
        raise FormulaSyntaxError(f"Unexpected token {token.value!r} in {self.formula!r}")


def parse_formula(formula: str) -> Node:
    return Parser(formula).parse()


def iter_refs(node: Node) -> Iterator[Ref | Range]:
    if isinstance(node, (Ref, Range)):
        yield node
    elif isinstance(node, Unary):
        yield from iter_refs(node.value)  # type: ignore[arg-type]
    elif isinstance(node, Binary):
        yield from iter_refs(node.left)  # type: ignore[arg-type]
        yield from iter_refs(node.right)  # type: ignore[arg-type]
    elif isinstance(node, Func):
        for arg in node.args:
            yield from iter_refs(arg)  # type: ignore[arg-type]


def _ref_fingerprint(ref: Ref, anchor: Address) -> str:
    a = ref.address
    row = f"R{a.row}" if a.row_abs else f"R[{a.row - anchor.row:+d}]"
    col = f"C{a.col}" if a.col_abs else f"C[{a.col - anchor.col:+d}]"
    sheet = f"'{ref.sheet}'!" if ref.sheet else ""
    return f"{sheet}{row}{col}"


def fingerprint(node: Node, anchor: Address) -> str:
    if isinstance(node, Number):
        return "NUM"
    if isinstance(node, Ref):
        return _ref_fingerprint(node, anchor)
    if isinstance(node, Range):
        return f"RANGE({_ref_fingerprint(node.start, anchor)}:{_ref_fingerprint(node.end, anchor)})"
    if isinstance(node, Unary):
        return f"U{node.op}({fingerprint(node.value, anchor)})"  # type: ignore[arg-type]
    if isinstance(node, Binary):
        return f"B{node.op}({fingerprint(node.left, anchor)},{fingerprint(node.right, anchor)})"  # type: ignore[arg-type]
    if isinstance(node, Func):
        return f"F{node.name}({','.join(fingerprint(a, anchor) for a in node.args)})"  # type: ignore[arg-type]
    raise TypeError(type(node))


def formula_fingerprint(formula: str, anchor_text: str) -> str:
    return fingerprint(parse_formula(formula), parse_address(anchor_text))


def _format_ref(ref: Ref) -> str:
    sheet = ""
    if ref.sheet:
        safe = ref.sheet.replace("'", "''")
        sheet = f"'{safe}'!"
    return sheet + ref.address.a1


def render(node: Node) -> str:
    if isinstance(node, Number):
        if node.source_text is not None:
            return node.source_text
        return str(int(node.value)) if node.value.is_integer() else repr(node.value)
    if isinstance(node, Ref):
        return _format_ref(node)
    if isinstance(node, Range):
        return f"{_format_ref(node.start)}:{_format_ref(node.end)}"
    if isinstance(node, Unary):
        return f"{node.op}{render(node.value)}"  # type: ignore[arg-type]
    if isinstance(node, Binary):
        return f"({render(node.left)}{node.op}{render(node.right)})"  # type: ignore[arg-type]
    if isinstance(node, Func):
        return f"{node.name}({','.join(render(a) for a in node.args)})"  # type: ignore[arg-type]
    raise TypeError(type(node))


def translate_formula(formula: str, source_anchor: str, target_anchor: str) -> str:
    source = parse_address(source_anchor)
    target = parse_address(target_anchor)
    drow, dcol = target.row - source.row, target.col - source.col
    prefix = "=" if formula.startswith("=") else ""
    body = formula[1:] if prefix else formula

    def repl(match: re.Match[str]) -> str:
        ref = _parse_ref(match.group())
        a = ref.address
        row = a.row if a.row_abs else a.row + drow
        col = a.col if a.col_abs else a.col + dcol
        if row < 1 or col < 1:
            return match.group()
        moved = Ref(Address(row=row, col=col, row_abs=a.row_abs, col_abs=a.col_abs), ref.sheet)
        return _format_ref(moved)

    return prefix + REF_RE.sub(repl, body)


def normalized_formula(formula: str) -> str:
    compact = re.sub(r"\s+", "", formula).upper()
    # Excel treats quotes around a simple sheet identifier as optional.
    # Canonicalizing this spelling prevents semantically identical repairs such
    # as Detail!B7 and 'Detail'!B7 from being scored as different formulas.
    return re.sub(r"'([A-Z_][A-Z0-9_.]*)'!", r"\1!", compact)


def edit_cost(left: str, right: str) -> float:
    ratio = SequenceMatcher(None, normalized_formula(left), normalized_formula(right)).ratio()
    return 0.5 + 4.0 * (1.0 - ratio)


def small_edit_candidates_with_kinds(formula: str) -> list[tuple[str, tuple[str, ...]]]:
    """Generate bounded one-edit repairs and auditable edit categories."""
    prefix = "=" if formula.startswith("=") else ""
    body = formula[1:] if prefix else formula
    candidates: dict[str, set[str]] = {}

    def add(candidate: str, kind: str) -> None:
        if candidate != formula:
            candidates.setdefault(candidate, set()).add(kind)

    # Operator substitutions.
    for match in re.finditer(r"[+\-*/]", body):
        for op in "+-*/":
            if op != match.group():
                add(prefix + body[:match.start()] + op + body[match.end():], "operator")

    # Function substitutions for the supported aggregate family.
    for match in re.finditer(r"\b(SUM|AVERAGE|MIN|MAX)\b", body, flags=re.IGNORECASE):
        for name in ("SUM", "AVERAGE", "MIN", "MAX"):
            if name != match.group().upper():
                add(prefix + body[:match.start()] + name + body[match.end():], "aggregate_function")

    # Shift one non-absolute reference by one row or column. This covers
    # boundary mistakes, copy offsets, and many absolute-reference failures.
    reference_matches = list(REF_RE.finditer(body))
    for match_index, match in enumerate(reference_matches):
        ref = _parse_ref(match.group())
        a = ref.address
        variants: list[Address] = []
        if not a.row_abs:
            for delta in (-1, 1):
                if a.row + delta >= 1:
                    variants.append(Address(a.row + delta, a.col, a.row_abs, a.col_abs))
        if not a.col_abs:
            for delta in (-1, 1):
                if a.col + delta >= 1:
                    variants.append(Address(a.row, a.col + delta, a.row_abs, a.col_abs))
        for moved in variants:
            replacement = _format_ref(Ref(moved, ref.sheet))
            before = body[:match.start()].rstrip()
            after = body[match.end():].lstrip()
            kind = "range_boundary" if before.endswith(":") or after.startswith(":") else "reference_shift"
            candidate = prefix + body[:match.start()] + replacement + body[match.end():]
            add(candidate, kind)
            if kind == "range_boundary" and moved.row != a.row:
                add(candidate, "range_boundary_row")
                if before.endswith(":"):
                    add(candidate, "range_boundary_end_row")
            if kind == "range_boundary" and moved.col != a.col and before.endswith(":"):
                add(candidate, "range_boundary_end_col")
            if kind == "reference_shift" and match_index == len(reference_matches) - 1:
                add(candidate, "copy_offset")
                if moved.row != a.row:
                    add(candidate, "copy_offset_row")

        # Toggle row/column anchoring independently. Toggling is intentionally
        # bounded to one axis so candidates remain explainable one-edit repairs.
        absolute_variants = {
            Address(a.row, a.col, not a.row_abs, a.col_abs),
            Address(a.row, a.col, a.row_abs, not a.col_abs),
        }
        for changed in absolute_variants:
            replacement = _format_ref(Ref(changed, ref.sheet))
            add(prefix + body[:match.start()] + replacement + body[match.end():], "absolute_reference")

        # A missing absolute reference is often revealed only after a copied
        # formula has shifted to a neighboring row or column.  Include bounded
        # repairs that both restore full anchoring and undo one copy offset.
        if not (a.row_abs and a.col_abs):
            fully_absolute_neighbors = []
            for row_delta, col_delta in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                if a.row + row_delta >= 1 and a.col + col_delta >= 1:
                    fully_absolute_neighbors.append(Address(
                        a.row + row_delta,
                        a.col + col_delta,
                        row_abs=True,
                        col_abs=True,
                    ))
            for changed in fully_absolute_neighbors:
                replacement = _format_ref(Ref(changed, ref.sheet))
                candidate = prefix + body[:match.start()] + replacement + body[match.end():]
                add(candidate, "absolute_reference")
                add(candidate, "reference_shift")
                compact_before = re.sub(r"\s+", "", body[:match.start()])
                if compact_before.endswith(("(1+", "(1-", "(100+", "(100-")):
                    add(candidate, "parameter_anchor")

    return [
        (candidate, tuple(sorted(kinds)))
        for candidate, kinds in sorted(candidates.items(), key=lambda item: (edit_cost(formula, item[0]), item[0]))
    ]


def small_edit_candidates(formula: str) -> list[str]:
    """Backward-compatible formula-only view of bounded one-edit repairs."""
    return [candidate for candidate, _ in small_edit_candidates_with_kinds(formula)]


def flatten_values(values: Iterable[object]) -> list[object]:
    flat: list[object] = []
    for value in values:
        if isinstance(value, list):
            flat.extend(flatten_values(value))
        else:
            flat.append(value)
    return flat


def numeric(value: object) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError("Non-finite numeric value")
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected numeric value, got {value!r}") from exc
