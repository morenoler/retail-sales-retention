"""Load the two original UCI workbook sheets into one SQLite database."""

from __future__ import annotations

import argparse
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "data" / "raw" / "online_retail_ii.zip"
DEFAULT_DB = ROOT / "data" / "retail.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_lines (
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    invoice_no TEXT,
    stock_code TEXT,
    description TEXT,
    quantity INTEGER,
    invoice_date TEXT,
    unit_price REAL,
    customer_id TEXT,
    country TEXT,
    PRIMARY KEY (source_sheet, source_row)
);
CREATE INDEX IF NOT EXISTS idx_lines_date ON invoice_lines(invoice_date);
CREATE INDEX IF NOT EXISTS idx_lines_customer_date ON invoice_lines(customer_id, invoice_date);
CREATE INDEX IF NOT EXISTS idx_lines_invoice ON invoice_lines(invoice_no);
"""


def clean_id(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and float(value).is_integer():
        return str(int(value))
    value = str(value).strip()
    return value or None


def load(archive: Path, db_path: Path) -> int:
    if not archive.exists():
        raise FileNotFoundError(
            f"Missing {archive}. Download Online Retail II from "
            "https://archive.ics.uci.edu/dataset/502/online+retail+ii"
        )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        with zipfile.ZipFile(archive) as zf:
            with zf.open("online_retail_II.xlsx") as source:
                workbook = load_workbook(source, read_only=True, data_only=True)
                total = 0
                for sheet in workbook:
                    batch = []
                    for row_number, values in enumerate(sheet.values, 1):
                        if row_number == 1:
                            continue
                        invoice, stock, description, quantity, date, price, customer, country = values
                        if isinstance(date, datetime):
                            date = date.isoformat(sep=" ", timespec="seconds")
                        batch.append((
                            sheet.title, row_number, clean_id(invoice), clean_id(stock),
                            description, quantity, date, price, clean_id(customer), country,
                        ))
                        if len(batch) == 10_000:
                            conn.executemany(
                                "INSERT INTO invoice_lines VALUES (?,?,?,?,?,?,?,?,?,?)", batch
                            )
                            total += len(batch)
                            batch.clear()
                    if batch:
                        conn.executemany(
                            "INSERT INTO invoice_lines VALUES (?,?,?,?,?,?,?,?,?,?)", batch
                        )
                        total += len(batch)
                    conn.commit()
                    print(f"{sheet.title}: loaded; cumulative rows {total:,}")
                workbook.close()
        return total
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    print(f"Loaded {load(args.archive, args.db):,} rows into {args.db}")
