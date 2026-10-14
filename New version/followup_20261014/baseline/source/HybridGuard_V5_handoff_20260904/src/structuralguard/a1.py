from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Address:
    row: int
    col: int
    row_abs: bool = False
    col_abs: bool = False


def column_to_number(text: str) -> int:
    result = 0
    for char in text.upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"invalid column: {text}")
        result = result * 26 + ord(char) - 64
    return result


def number_to_column(value: int) -> str:
    if value < 1:
        raise ValueError("column number must be positive")
    chars: list[str] = []
    while value:
        value, rem = divmod(value - 1, 26)
        chars.append(chr(65 + rem))
    return "".join(reversed(chars))


def parse_address(text: str) -> Address:
    import re

    match = re.fullmatch(r"(\$?)([A-Za-z]{1,3})(\$?)([1-9][0-9]*)", text)
    if not match:
        raise ValueError(f"invalid A1 address: {text}")
    return Address(
        row=int(match.group(4)),
        col=column_to_number(match.group(2)),
        row_abs=bool(match.group(3)),
        col_abs=bool(match.group(1)),
    )


def format_address(address: Address) -> str:
    return (
        ("$" if address.col_abs else "")
        + number_to_column(address.col)
        + ("$" if address.row_abs else "")
        + str(address.row)
    )
