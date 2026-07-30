"""Validate Bazaar's model. Every check here is a bug this course teaches you to prevent.

A model is not "done" when the SQL runs. It is done when these pass - and when they run on
every load, so a broken model fails loudly instead of quietly producing a wrong dashboard.

Nine checks, in the order things actually go wrong:
    1. grain      - is one row really one thing? (duplicate keys)
    2. keys       - are primary keys unique and non-null?
    3. integrity  - does every fact FK resolve to a dimension row?
    4. unknowns   - what share of facts landed on the -1 unknown member?
    5. scd2       - does every business key have exactly one current version?
    6. additivity - do the derived money columns still equal their parts?
    7. reconcile  - does the star still agree with the OLTP source?
    8. marts      - do the marts agree with the facts they aggregate?
    9. nulls      - are dimension attributes free of NULLs?

Usage:
    python python/validate_model.py
    python python/validate_model.py --verbose     # print every check, not just failures
Exit code is 1 if any check fails, so this drops straight into CI.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "bazaar.db"

# Each check: (group, name, sql, expectation). The SQL returns one row, one column.
# `expect` is a callable on that value; `explain` says what a failure means.
CHECKS: list[tuple[str, str, str, str]] = [
    # ---- 1. grain -----------------------------------------------------------
    ("grain", "fact_order_item is one row per order line", """
        SELECT COUNT(*) FROM (
          SELECT order_id, line_no FROM fact_order_item
          GROUP BY order_id, line_no HAVING COUNT(*) > 1)
    """, "duplicate (order_id, line_no) means the grain sentence is a lie and every SUM double-counts"),

    ("grain", "fact_transaction is one row per attempt", """
        SELECT COUNT(*) FROM (
          SELECT txn_id FROM fact_transaction GROUP BY txn_id HAVING COUNT(*) > 1)
    """, "duplicate txn_id inflates settled money"),

    ("grain", "fact_cart is one row per cart", """
        SELECT COUNT(*) FROM (
          SELECT cart_id FROM fact_cart GROUP BY cart_id HAVING COUNT(*) > 1)
    """, "duplicate cart_id inflates demand and abandonment"),

    ("grain", "mart_merchant_daily is one row per merchant per day", """
        SELECT COUNT(*) FROM (
          SELECT activity_date, merchant_id FROM mart_merchant_daily
          GROUP BY activity_date, merchant_id HAVING COUNT(*) > 1)
    """, "a mart that fans out is worse than no mart - it looks authoritative"),

    # ---- 2. keys ------------------------------------------------------------
    ("keys", "dim_user business key is unique", """
        SELECT COUNT(*) FROM (
          SELECT user_id FROM dim_user GROUP BY user_id HAVING COUNT(*) > 1)
    """, "a type-1 dimension with a repeated business key fans out every join"),

    ("keys", "dim_payment_method has no null natural key", """
        SELECT COUNT(*) FROM dim_payment_method WHERE payment_method IS NULL
    """, "a NULL natural key can never be matched by a load"),

    # ---- 3. referential integrity ------------------------------------------
    ("integrity", "every fact_order_item date_key exists in dim_date", """
        SELECT COUNT(*) FROM fact_order_item f
        LEFT JOIN dim_date d ON d.date_key = f.date_key WHERE d.date_key IS NULL
    """, "an orphan fact disappears from every inner-join query - silent revenue loss"),

    ("integrity", "every fact_order_item merchant_sk exists in dim_merchant", """
        SELECT COUNT(*) FROM fact_order_item f
        LEFT JOIN dim_merchant m ON m.merchant_sk = f.merchant_sk WHERE m.merchant_sk IS NULL
    """, "orphan merchant keys drop rows from merchant reporting"),

    ("integrity", "every fact_order_item product_sk exists in dim_product", """
        SELECT COUNT(*) FROM fact_order_item f
        LEFT JOIN dim_product p ON p.product_sk = f.product_sk WHERE p.product_sk IS NULL
    """, "orphan product keys drop rows from product reporting"),

    ("integrity", "every fact_transaction payment_method_key exists", """
        SELECT COUNT(*) FROM fact_transaction f
        LEFT JOIN dim_payment_method pm ON pm.payment_method_key = f.payment_method_key
        WHERE pm.payment_method_key IS NULL
    """, "a new payment method in the source with no dimension row"),

    # ---- 5. SCD2 -----------------------------------------------------------
    ("scd2", "each merchant has exactly one current version", """
        SELECT COUNT(*) FROM (
          SELECT merchant_id FROM dim_merchant WHERE is_current = 1
          GROUP BY merchant_id HAVING COUNT(*) > 1)
    """, "two current rows for one merchant doubles that merchant's revenue on join"),

    ("scd2", "each product has exactly one current version", """
        SELECT COUNT(*) FROM (
          SELECT product_id FROM dim_product WHERE is_current = 1
          GROUP BY product_id HAVING COUNT(*) > 1)
    """, "two current rows for one product doubles that product's revenue on join"),

    ("scd2", "no SCD2 row has valid_from after valid_to", """
        SELECT (SELECT COUNT(*) FROM dim_merchant WHERE valid_from > valid_to)
             + (SELECT COUNT(*) FROM dim_product  WHERE valid_from > valid_to)
    """, "an inverted validity window matches nothing, so its facts fall through"),

    # ---- 6. additivity ------------------------------------------------------
    ("additivity", "net_amount = gross_amount - discount_amount", """
        SELECT COUNT(*) FROM fact_order_item
        WHERE ABS(net_amount - (gross_amount - discount_amount)) > 0.01
    """, "a derived measure that no longer equals its parts - the model is internally inconsistent"),

    ("additivity", "gross_amount = quantity * unit_price", """
        SELECT COUNT(*) FROM fact_order_item
        WHERE ABS(gross_amount - quantity * unit_price) > 0.01
    """, "the measure and its rate disagree"),

    ("additivity", "margin_amount = net_amount - cost_amount", """
        SELECT COUNT(*) FROM fact_order_item
        WHERE ABS(margin_amount - (net_amount - cost_amount)) > 0.01
    """, "margin drifted from its own definition"),

    ("additivity", "approved_amount is zero unless approved", """
        SELECT COUNT(*) FROM fact_transaction WHERE is_approved = 0 AND approved_amount <> 0
    """, "a pre-split measure that is not actually split stops being additive"),

    ("additivity", "abandoned_value is zero for converted carts", """
        SELECT COUNT(*) FROM fact_cart WHERE converted_flag = 1 AND abandoned_value <> 0
    """, "abandoned value leaking into converted carts overstates lost demand"),

    ("additivity", "no transaction is both approved and declined", """
        SELECT COUNT(*) FROM fact_transaction WHERE is_approved = 1 AND is_declined = 1
    """, "mutually exclusive flags that overlap break every rate computed from them"),

    # ---- 7. reconciliation to source ---------------------------------------
    ("reconcile", "fact_order_item row count equals order_items", """
        SELECT ABS((SELECT COUNT(*) FROM fact_order_item) - (SELECT COUNT(*) FROM order_items))
    """, "the load dropped or duplicated source rows"),

    ("reconcile", "fact_transaction row count equals transactions", """
        SELECT ABS((SELECT COUNT(*) FROM fact_transaction) - (SELECT COUNT(*) FROM transactions))
    """, "the load dropped or duplicated payment attempts"),

    ("reconcile", "star net revenue equals source net revenue (to the cent)", """
        SELECT CAST(ABS(
          (SELECT SUM(net_amount) FROM fact_order_item)
          - (SELECT SUM(quantity * unit_price - discount_amt) FROM order_items)
        ) > 0.01 AS INTEGER)
    """, "the single most important check in the file: the warehouse disagrees with the system of record"),

    # ---- 8. mart agreement --------------------------------------------------
    ("marts", "mart_merchant_daily revenue equals paid fact revenue", """
        SELECT CAST(ABS(
          (SELECT SUM(net_revenue) FROM mart_merchant_daily)
          - (SELECT SUM(net_amount) FROM fact_order_item WHERE is_paid = 1)
        ) > 0.01 AS INTEGER)
    """, "a mart that disagrees with its fact is a second source of truth"),

    ("marts", "mart_hourly_transactions attempts equals fact_transaction rows", """
        SELECT ABS((SELECT SUM(attempts) FROM mart_hourly_transactions)
                 - (SELECT COUNT(*) FROM fact_transaction))
    """, "the hourly mart lost or duplicated attempts"),

    ("marts", "mart_funnel_daily carts equals fact_cart rows", """
        SELECT ABS((SELECT SUM(carts_created) FROM mart_funnel_daily)
                 - (SELECT COUNT(*) FROM fact_cart))
    """, "the funnel mart lost or duplicated carts"),

    # ---- 9. nulls in dimension attributes ----------------------------------
    ("nulls", "dim_user has no NULL attributes", """
        SELECT COUNT(*) FROM dim_user
        WHERE country IS NULL OR city IS NULL OR acquisition_channel IS NULL
           OR tenure_bucket IS NULL
    """, "a NULL attribute silently drops rows from every inner join and every GROUP BY bucket"),

    ("nulls", "dim_product has no NULL attributes", """
        SELECT COUNT(*) FROM dim_product
        WHERE category IS NULL OR merchant_name IS NULL OR price_tier IS NULL OR status IS NULL
    """, "same failure mode, on the product side"),
]

# Checks that report a share rather than pass/fail. Printed for judgement, not enforced.
GAUGES: list[tuple[str, str]] = [
    ("unknown-member rate, fact_order_item merchants",
     "SELECT ROUND(100.0 * SUM(merchant_sk = -1) / COUNT(*), 2) FROM fact_order_item"),
    ("unknown-member rate, fact_order_item products",
     "SELECT ROUND(100.0 * SUM(product_sk = -1) / COUNT(*), 2) FROM fact_order_item"),
    ("unknown-member rate, fact_transaction payment methods",
     "SELECT ROUND(100.0 * SUM(payment_method_key = -1) / COUNT(*), 2) FROM fact_transaction"),
    ("share of order lines that settled",
     "SELECT ROUND(100.0 * SUM(is_paid) / COUNT(*), 2) FROM fact_order_item"),
    ("cart conversion rate",
     "SELECT ROUND(100.0 * SUM(converted_flag) / COUNT(*), 2) FROM fact_cart"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"{args.db} not found - run python/build_star.py first")

    conn = sqlite3.connect(args.db)
    failures: list[tuple[str, str, int, str]] = []
    passed = 0

    print(f"Validating {args.db.name} - {len(CHECKS)} checks\n")
    current_group = None
    for group, name, sql, explain in CHECKS:
        if args.verbose and group != current_group:
            print(f"[{group}]")
            current_group = group
        value = conn.execute(sql).fetchone()[0] or 0
        if value == 0:
            passed += 1
            if args.verbose:
                print(f"  PASS  {name}")
        else:
            failures.append((group, name, value, explain))
            print(f"  FAIL  [{group}] {name}")
            print(f"        offending rows: {value}")
            print(f"        why it matters: {explain}")

    print(f"\nGauges (judgement, not pass/fail)")
    for label, sql in GAUGES:
        print(f"  {label:<48} {conn.execute(sql).fetchone()[0]}%")

    conn.close()
    print(f"\n{passed}/{len(CHECKS)} checks passed.")
    if failures:
        print(f"{len(failures)} FAILED - the model is not safe to publish.")
        sys.exit(1)
    print("Model is internally consistent and reconciles to the source.")


if __name__ == "__main__":
    main()
