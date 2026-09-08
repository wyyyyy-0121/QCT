"""A1 address helpers used by the parser, graph, and benchmark evaluator."""

from __future__ import annotations

import re
from dataclasses import dataclass

CELL_RE = re.compile(r"^(?P<col_abs>\$?)(?P<col>[A-Za-z]{1,3})(?P<row_abs>\$?)(?P<row>[1-9]\d*)$")


def col_to_num(col: str) -> int:
    value = 0
    for char in col.upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"Invalid column: {col}")
        value = value * 26 + ord(char) - 64
    return value


def num_to_col(value: int) -> str:
    if value < 1:
        raise ValueError(f"Column must be positive: {value}")
    chars: list[str] = []
    while value:
        value, rem = divmod(value - 1, 26)
        chars.append(chr(65 + rem))
    return "".join(reversed(chars))


@dataclass(frozen=True, order=True)
class Address:
    row: int
    col: int
    row_abs: bool = False
    col_abs: bool = False

    @property
    def a1(self) -> str:
        return f"{'$' if self.col_abs else ''}{num_to_col(self.col)}{'$' if self.row_abs else ''}{self.row}"


def parse_address(text: str) -> Address:
    match = CELL_RE.match(text)
    if not match:
        raise ValueError(f"Invalid A1 cell address: {text}")
    return Address(
        row=int(match.group("row")),
        col=col_to_num(match.group("col")),
        row_abs=bool(match.group("row_abs")),
        col_abs=bool(match.group("col_abs")),
    )


def plain_address(text: str) -> str:
    addr = parse_address(text)
    return f"{num_to_col(addr.col)}{addr.row}"


def iter_rect(start: Address, end: Address):
    r1, r2 = sorted((start.row, end.row))
    c1, c2 = sorted((start.col, end.col))
    for row in range(r1, r2 + 1):
        for col in range(c1, c2 + 1):
            yield f"{num_to_col(col)}{row}"

