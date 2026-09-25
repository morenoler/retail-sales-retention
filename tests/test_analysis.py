import sqlite3
import unittest
from pathlib import Path

from src.build_db import SCHEMA
from src.make_report import month_offset


class AnalysisTests(unittest.TestCase):
    def test_overlapping_sheet_rows_count_once(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(SCHEMA)
            rows = [
                ("Year 2009-2010", 2, "100", "A", "Item", 2, "2010-12-05 10:00:00", 3.0, "7", "UK"),
                ("Year 2010-2011", 2, "100", "A", "Item", 2, "2010-12-05 10:00:00", 3.0, "7", "UK"),
                ("Year 2010-2011", 3, "101", "B", "Item", 1, "2010-12-11 10:00:00", 5.0, "7", "UK"),
                ("Year 2010-2011", 4, "C102", "B", "Item", -1, "2010-12-11 11:00:00", 5.0, "7", "UK"),
            ]
            conn.executemany("INSERT INTO invoice_lines VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            sql = (Path(__file__).resolve().parents[1] / "sql" / "analysis.sql").read_text(encoding="utf-8").split("-- Query 1:")[0]
            conn.executescript(sql)
            self.assertEqual(conn.execute("SELECT count(*) FROM canonical_lines").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT sum(line_value) FROM valid_sales").fetchone()[0], 11.0)
        finally:
            conn.close()

    def test_cohort_month_crosses_year(self):
        self.assertEqual(month_offset("2010-11", 3), "2011-02")


if __name__ == "__main__":
    unittest.main()
