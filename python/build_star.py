"""Build Bazaar's warehouse: OLTP source -> star schema -> marts -> agent views.

Runs the SQL files in order against a SQLite database file, so every later script (and every
question in sql/30_business_questions.sql) has something to query. This is the whole model in
one command.

Usage:
    python python/gen_bazaar_data.py        # first, generates the source data
    python python/build_star.py             # then, builds bazaar.db
    python python/build_star.py --fresh     # delete and rebuild from scratch
    python python/build_star.py --db /tmp/x.db
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL = ROOT / "sql"
DEFAULT_DB = ROOT / "bazaar.db"

# Order matters: dimensions before facts, facts before marts, marts before views.
BUILD_ORDER = [
    ("01_oltp_ddl.sql", "OLTP schema (b3-b4)"),
    ("02_seed.sql", "OLTP source data"),
    ("10_dim_ddl.sql", "dimensions (b6)"),
    ("11_fact_ddl.sql", "facts (b7)"),
    ("12_oltp_to_star.sql", "load the star (b6-b7)"),
    ("20_marts.sql", "marts (b8)"),
    ("40_agent_views.sql", "agent views + semantic layer (b9)"),
]

COUNT_TABLES = [
    "users", "merchants", "products", "carts", "cart_items", "orders", "order_items",
    "transactions", "dim_date", "dim_time_of_day", "dim_user", "dim_merchant",
    "dim_product", "dim_payment_method", "fact_order_item", "fact_transaction",
    "fact_cart", "mart_merchant_daily", "mart_hourly_transactions", "mart_funnel_daily",
    "mart_payment_health_daily", "v_metric_definitions",
]


def build(db_path: Path, fresh: bool) -> None:
    if fresh and db_path.exists():
        db_path.unlink()
        print(f"removed {db_path.name}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")   # declared FKs are only enforced when this is on

    for filename, label in BUILD_ORDER:
        path = SQL / filename
        if not path.exists():
            raise SystemExit(f"missing {path} - run python/gen_bazaar_data.py first")
        start = time.perf_counter()
        conn.executescript(path.read_text())
        conn.commit()
        print(f"  ran {filename:<24} {label:<38} {(time.perf_counter() - start) * 1000:6.0f} ms")

    print(f"\n{'object':<28}{'rows':>9}")
    print("-" * 37)
    for table in COUNT_TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:<28}{n:>9,}")

    conn.close()
    print(f"\nBuilt {db_path}")
    print("Next: python python/validate_model.py   then   python python/answer_questions.py")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--fresh", action="store_true", help="delete the database first")
    args = ap.parse_args()
    build(args.db, args.fresh)


if __name__ == "__main__":
    main()
