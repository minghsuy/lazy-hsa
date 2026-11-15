"""Pytest fixtures for lazy-hsa tests."""

import re

import pytest


@pytest.fixture
def family_members():
    """Default family members list."""
    return ["Alice", "Bob", "Charlie"]


@pytest.fixture
def mock_extractor():
    """Create a mock extractor for testing without LLM calls."""
    from src.processors.llm_extractor import MockVisionExtractor

    return MockVisionExtractor()


class FakeWorksheet:
    """In-memory stand-in for the gspread worksheet calls GSheetsClient makes.

    get_all_records() zips the header row with each row the way gspread does, so
    a value sitting under no header is dropped on read - the behavior the Review
    Status writer guard exists for.
    """

    def __init__(self, header: list[str], rows: list[list] | None = None):
        self.header = list(header)
        self.rows = [list(r) for r in rows or []]
        self.col_count = len(self.header)
        self.acell_writes: list[tuple[str, object]] = []

    def row_values(self, row: int) -> list:
        assert row == 1, "GSheetsClient only reads the header row this way"
        return list(self.header)

    def get_all_values(self) -> list[list]:
        return [list(self.header)] + [list(r) for r in self.rows]

    def get_all_records(self) -> list[dict]:
        width = len(self.header)
        return [
            dict(zip(self.header, r + [""] * (width - len(r)), strict=False)) for r in self.rows
        ]

    def append_row(self, row: list, value_input_option: str = "RAW") -> None:
        self.rows.append(list(row))

    def resize(self, cols: int) -> None:
        self.col_count = cols

    def delete_rows(self, index: int) -> None:
        del self.rows[index - 2]

    def update_acell(self, label: str, value) -> None:
        self.acell_writes.append((label, value))
        letters, number = re.fullmatch(r"([A-Z]+)(\d+)", label).groups()
        col = 0
        for ch in letters:
            col = col * 26 + (ord(ch) - ord("A") + 1)
        target = self.header if int(number) == 1 else self.rows[int(number) - 2]
        target.extend([""] * (col - len(target)))
        target[col - 1] = value


@pytest.fixture
def sheets_client():
    """Factory for a GSheetsClient backed by a FakeWorksheet (default: current HEADERS)."""
    from src.storage.sheet_client import GSheetsClient

    def make(header: list[str] | None = None, rows: list[list] | None = None):
        client = GSheetsClient.__new__(GSheetsClient)
        client._worksheet = FakeWorksheet(GSheetsClient.HEADERS if header is None else header, rows)
        return client

    return make
