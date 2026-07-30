"""Generate the Bazaar marketplace source data used by every session in this course.

Bazaar is a multi-merchant ecommerce marketplace. This script writes the OLTP
source system - the eight tables you design in sessions b1-b4 - as CSV files,
as a SQL seed script, and as the browser seed the live labs on the site read.

Everything is deterministic (seed 42), so your numbers match the numbers printed
on the course pages exactly. Four stories are baked into the data on purpose,
because sessions b8 and b9 ask you to find them:

  1. Merchant M07 (Nimbus Audio) loses most of its revenue in the last two
     weeks - part fewer orders, part a payment-decline spike, part its best
     product going out of stock on 2026-06-15.
  2. A single-day sales dip on 2026-06-10: a checkout incident declined roughly
     half of that day's payment attempts. Order rows exist, money does not.
  3. Transaction volume peaks at 12:00-13:00 and again at 20:00-22:00, so
     "what are our peak hours" has a real, defensible answer.
  4. A paid-search budget cut on 2026-06-18 drops top-of-funnel demand about
     30%, so the quarter-end sales drop has TWO causes - a demand shock and one
     merchant collapsing - and session b8 has to separate them.

Usage:
    python python/gen_bazaar_data.py            # writes data/, sql/02_seed.sql, assets/bazaar-seed.js
    python python/gen_bazaar_data.py --rows     # also print row counts
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass, asdict, fields
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 42
START = date(2026, 4, 1)
DAYS = 90
END = START + timedelta(days=DAYS - 1)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SQL = ROOT / "sql"
ASSETS = ROOT / "assets"

INCIDENT_DAY = date(2026, 6, 10)          # checkout outage - decline storm
NIMBUS_DECLINE_FROM = date(2026, 6, 16)   # merchant M07 slide starts
OOS_DAY = date(2026, 6, 15)               # M07 hero product goes out of stock
PULLBACK_DAY = date(2026, 6, 18)          # paid-search budget cut - demand shock

# ---------------------------------------------------------------- reference data

MERCHANTS = [
    # id, name, category, country, tier, commission_pct
    ("M01", "Kettle & Co",      "Home",        "SG", "gold",     0.12),
    ("M02", "Verdant Skincare", "Beauty",      "SG", "gold",     0.15),
    ("M03", "Northlight Books", "Media",       "MY", "silver",   0.10),
    ("M04", "Pace Athletics",   "Sport",       "SG", "gold",     0.13),
    ("M05", "Tiny Fern",        "Home",        "ID", "bronze",   0.18),
    ("M06", "Copper Kitchen",   "Home",        "SG", "silver",   0.12),
    ("M07", "Nimbus Audio",     "Electronics", "SG", "platinum", 0.09),
    ("M08", "Loom & Thread",    "Apparel",     "VN", "silver",   0.14),
    ("M09", "Harbour Pet",      "Pet",         "SG", "bronze",   0.17),
    ("M10", "Sable Stationery", "Office",      "MY", "bronze",   0.16),
    ("M11", "Orchid Grocer",    "Grocery",     "SG", "silver",   0.11),
    ("M12", "Fable Toys",       "Toys",        "SG", "bronze",   0.16),
]

PRODUCT_WORDS = {
    "Home":        ["Pour-Over Kettle", "Linen Throw", "Ceramic Vase", "Rattan Basket", "Oak Tray"],
    "Beauty":      ["Vitamin C Serum", "Clay Mask", "Rose Toner", "Night Balm", "Lip Oil"],
    "Media":       ["Hardcover Novel", "Poetry Anthology", "Art Monograph", "Cookbook", "Atlas"],
    "Sport":       ["Trail Runners", "Yoga Mat", "Resistance Set", "Cycling Bidon", "Tempo Shorts"],
    "Electronics": ["Studio Headphones", "Desk Mic", "Bluetooth Speaker", "USB-C Interface", "Earbuds Pro"],
    "Apparel":     ["Oxford Shirt", "Merino Tee", "Canvas Tote", "Wool Scarf", "Chino Trousers"],
    "Pet":         ["Slow Feeder", "Rope Toy", "Cat Tunnel", "Grooming Brush", "Travel Bowl"],
    "Office":      ["Dot Grid Notebook", "Fineliner Set", "Desk Mat", "Index Cards", "Kraft Folder"],
    "Grocery":     ["Cold Brew Pack", "Chili Crisp", "Sea Salt Flakes", "Olive Oil 500ml", "Rice Crackers"],
    "Toys":        ["Wooden Blocks", "Puzzle 500pc", "Plush Otter", "Marble Run", "Card Game"],
}

COUNTRIES = [("SG", "Singapore"), ("MY", "Kuala Lumpur"), ("ID", "Jakarta"),
             ("VN", "Ho Chi Minh"), ("AU", "Melbourne")]
CHANNELS = ["organic", "paid_search", "social", "email", "referral"]
PAYMENT_METHODS = ["card_visa", "card_mastercard", "card_amex", "paynow", "grabpay", "bank_transfer"]
DECLINE_REASONS = ["insufficient_funds", "expired_card", "do_not_honour", "3ds_failed", "gateway_timeout"]

# hourly weights: quiet night, lunch peak, big evening peak
HOUR_WEIGHTS = [1, 1, 1, 1, 1, 2, 4, 7, 9, 11, 13, 16,
                22, 21, 15, 13, 14, 17, 20, 26, 30, 28, 16, 7]


# ---------------------------------------------------------------- row shapes

@dataclass
class User:
    user_id: int
    email: str
    signup_ts: str
    country: str
    city: str
    acquisition_channel: str
    is_guest: int


@dataclass
class Merchant:
    merchant_id: str
    merchant_name: str
    category: str
    country: str
    tier: str
    commission_pct: float
    joined_date: str


@dataclass
class Product:
    product_id: int
    merchant_id: str
    sku: str
    product_name: str
    category: str
    list_price: float
    unit_cost: float
    launched_date: str
    status: str


@dataclass
class Cart:
    cart_id: int
    user_id: int
    created_ts: str
    status: str


@dataclass
class CartItem:
    cart_id: int
    product_id: int
    quantity: int
    added_ts: str


@dataclass
class Order:
    order_id: int
    user_id: int
    cart_id: int
    order_ts: str
    status: str
    ship_country: str
    currency: str


@dataclass
class OrderItem:
    order_id: int
    line_no: int
    product_id: int
    merchant_id: str
    quantity: int
    unit_price: float
    discount_amt: float


@dataclass
class Transaction:
    txn_id: int
    order_id: int
    txn_ts: str
    amount: float
    currency: str
    payment_method: str
    status: str
    decline_reason: str | None
    psp_ref: str


# ---------------------------------------------------------------- helpers

def ts(d: date, hour: int, minute: int, second: int) -> str:
    return datetime(d.year, d.month, d.day, hour, minute, second).strftime("%Y-%m-%d %H:%M:%S")


def pick_hour(rng: random.Random) -> int:
    return rng.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]


def money(x: float) -> float:
    return round(x + 1e-9, 2)


def daily_order_target(rng: random.Random, d: date) -> int:
    """Baseline volume with a weekly rhythm, mild growth, and one demand shock."""
    day_index = (d - START).days
    base = 9 + day_index * 0.045                      # slow growth over the quarter
    weekend = 1.25 if d.weekday() >= 5 else 1.0
    # story 4: paid-search budget is cut on 2026-06-18, so top-of-funnel demand
    # falls about 30%. This is the SECOND cause of the quarter-end sales drop -
    # session b8 has to separate it from merchant M07's collapse.
    pullback = 0.70 if d >= PULLBACK_DAY else 1.0
    noise = rng.uniform(0.85, 1.15)
    return max(3, int(round(base * weekend * pullback * noise)))


# ---------------------------------------------------------------- generation

def generate() -> dict[str, list]:
    rng = random.Random(SEED)

    # ---- users
    users: list[User] = []
    for uid in range(1, 61):
        cc, city = rng.choice(COUNTRIES)
        signup = START - timedelta(days=rng.randint(0, 400))
        users.append(User(
            user_id=uid,
            email=f"user{uid:03d}@example.com",
            signup_ts=ts(signup, pick_hour(rng), rng.randint(0, 59), rng.randint(0, 59)),
            country=cc,
            city=city,
            acquisition_channel=rng.choice(CHANNELS),
            is_guest=1 if uid % 17 == 0 else 0,
        ))

    # ---- merchants
    merchants = [
        Merchant(mid, name, cat, cc, tier, pct,
                 (START - timedelta(days=rng.randint(120, 900))).isoformat())
        for mid, name, cat, cc, tier, pct in MERCHANTS
    ]

    # ---- products (5 per merchant)
    products: list[Product] = []
    pid = 1000
    for m in merchants:
        for word in PRODUCT_WORDS[m.category]:
            pid += 1
            price = money(rng.choice([12.9, 18.5, 24.0, 32.9, 45.0, 59.9, 79.0, 129.0, 189.0]))
            products.append(Product(
                product_id=pid,
                merchant_id=m.merchant_id,
                sku=f"{m.merchant_id}-{pid}",
                product_name=word,
                category=m.category,
                list_price=price,
                unit_cost=money(price * rng.uniform(0.42, 0.68)),
                launched_date=(START - timedelta(days=rng.randint(30, 600))).isoformat(),
                status="active",
            ))

    by_merchant: dict[str, list[Product]] = {}
    for p in products:
        by_merchant.setdefault(p.merchant_id, []).append(p)

    # M07's hero product - the one that goes out of stock mid-June
    hero = by_merchant["M07"][0]
    hero.status = "out_of_stock"

    # merchant selection weights (M07 is a top seller until it slides)
    weights_base = {m.merchant_id: 1.0 for m in merchants}
    weights_base.update({"M07": 3.2, "M01": 2.0, "M04": 1.8, "M02": 1.6, "M11": 1.5})

    carts: list[Cart] = []
    cart_items: list[CartItem] = []
    orders: list[Order] = []
    order_items: list[OrderItem] = []
    txns: list[Transaction] = []

    cart_id = order_id = txn_id = 0

    for day_offset in range(DAYS):
        d = START + timedelta(days=day_offset)
        n_orders = daily_order_target(rng, d)

        # story 1: M07 loses share in the final two weeks
        weights = dict(weights_base)
        if d >= NIMBUS_DECLINE_FROM:
            weights["M07"] = 1.1

        # every order is preceded by a cart; extra carts are abandoned
        n_carts = int(round(n_orders / 0.45))

        for _ in range(n_carts):
            cart_id += 1
            u = rng.choice(users)
            hour = pick_hour(rng)
            created = ts(d, hour, rng.randint(0, 59), rng.randint(0, 59))

            mids = list(weights)
            mid = rng.choices(mids, weights=[weights[m] for m in mids], k=1)[0]
            pool = [p for p in by_merchant[mid] if not (p.status == "out_of_stock" and d >= OOS_DAY)]
            if not pool:
                pool = by_merchant[mid]
            n_lines = rng.choices([1, 2, 3], weights=[62, 27, 11], k=1)[0]
            chosen = rng.sample(pool, k=min(n_lines, len(pool)))

            qty_of: dict[int, int] = {}
            for p in chosen:
                qty = rng.choices([1, 2, 3], weights=[74, 20, 6], k=1)[0]
                qty_of[p.product_id] = qty
                cart_items.append(CartItem(
                    cart_id=cart_id,
                    product_id=p.product_id,
                    quantity=qty,
                    added_ts=created,
                ))

            if rng.random() >= 0.45:
                carts.append(Cart(cart_id, u.user_id, created, "abandoned"))
                continue

            carts.append(Cart(cart_id, u.user_id, created, "converted"))

            # ---- order from the cart, a few minutes later
            order_id += 1
            o_minute = rng.randint(1, 25)
            o_dt = datetime(d.year, d.month, d.day, hour, rng.randint(0, 59), rng.randint(0, 59)) \
                + timedelta(minutes=o_minute)
            orders.append(Order(
                order_id=order_id,
                user_id=u.user_id,
                cart_id=cart_id,
                order_ts=o_dt.strftime("%Y-%m-%d %H:%M:%S"),
                status="placed",
                ship_country=u.country,
                currency="SGD",
            ))

            gross = 0.0
            for line_no, p in enumerate(chosen, start=1):
                qty = qty_of[p.product_id]
                disc_pct = rng.choices([0.0, 0.05, 0.10], weights=[70, 20, 10], k=1)[0]
                unit = p.list_price
                discount = money(unit * qty * disc_pct)
                order_items.append(OrderItem(
                    order_id=order_id, line_no=line_no, product_id=p.product_id,
                    merchant_id=p.merchant_id, quantity=qty,
                    unit_price=unit, discount_amt=discount,
                ))
                gross += unit * qty - discount

            amount = money(gross)

            # ---- payment attempts
            decline_rate = 0.06
            if d == INCIDENT_DAY:
                decline_rate = 0.55                    # story 2: checkout incident
            if mid == "M07" and d >= NIMBUS_DECLINE_FROM:
                decline_rate = 0.22                    # story 1: decline spike too

            method = rng.choices(PAYMENT_METHODS, weights=[34, 26, 6, 18, 12, 4], k=1)[0]
            attempt_dt = o_dt + timedelta(seconds=rng.randint(20, 240))
            declined = rng.random() < decline_rate

            txn_id += 1
            if declined:
                txns.append(Transaction(
                    txn_id=txn_id, order_id=order_id,
                    txn_ts=attempt_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    amount=amount, currency="SGD", payment_method=method,
                    status="declined",
                    decline_reason=("gateway_timeout" if d == INCIDENT_DAY
                                    else rng.choice(DECLINE_REASONS)),
                    psp_ref=f"psp_{txn_id:06d}",
                ))
                # about half of declined orders retry and succeed
                if rng.random() < 0.5:
                    txn_id += 1
                    retry_dt = attempt_dt + timedelta(minutes=rng.randint(2, 90))
                    txns.append(Transaction(
                        txn_id=txn_id, order_id=order_id,
                        txn_ts=retry_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        amount=amount, currency="SGD", payment_method=method,
                        status="approved", decline_reason=None,
                        psp_ref=f"psp_{txn_id:06d}",
                    ))
                    orders[-1].status = "paid"
                else:
                    orders[-1].status = "payment_failed"
            else:
                txns.append(Transaction(
                    txn_id=txn_id, order_id=order_id,
                    txn_ts=attempt_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    amount=amount, currency="SGD", payment_method=method,
                    status="approved", decline_reason=None,
                    psp_ref=f"psp_{txn_id:06d}",
                ))
                orders[-1].status = "paid"

            # a small share of paid orders are refunded later
            if orders[-1].status == "paid" and rng.random() < 0.04:
                txn_id += 1
                refund_dt = attempt_dt + timedelta(days=rng.randint(2, 14))
                if refund_dt.date() <= END:
                    txns.append(Transaction(
                        txn_id=txn_id, order_id=order_id,
                        txn_ts=refund_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        amount=-amount, currency="SGD", payment_method=method,
                        status="refunded", decline_reason=None,
                        psp_ref=f"psp_{txn_id:06d}",
                    ))
                    orders[-1].status = "refunded"

    return {
        "users": users, "merchants": merchants, "products": products,
        "carts": carts, "cart_items": cart_items, "orders": orders,
        "order_items": order_items, "transactions": txns,
    }


# ---------------------------------------------------------------- writers

def write_csvs(tables: dict[str, list]) -> None:
    DATA.mkdir(exist_ok=True)
    for name, rows in tables.items():
        cols = [f.name for f in fields(rows[0])]
        with (DATA / f"{name}.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow(asdict(r))


def sql_literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


# The schema itself lives in sql/01_oltp_ddl.sql - hand-written and commented,
# because the DDL IS the lesson. This script only fills it.

def insert_block(name: str, rows: list) -> str:
    cols = [f.name for f in fields(rows[0])]
    out = [f"INSERT INTO {name} ({', '.join(cols)}) VALUES"]
    vals = []
    for r in rows:
        d = asdict(r)
        vals.append(" (" + ",".join(sql_literal(d[c]) for c in cols) + ")")
    out.append(",\n".join(vals) + ";")
    return "\n".join(out)


def write_sql_seed(tables: dict[str, list]) -> str:
    SQL.mkdir(exist_ok=True)
    parts = [
        "-- 02_seed.sql - Bazaar OLTP source data (generated by python/gen_bazaar_data.py, seed 42)",
        "-- Data only. Run sql/01_oltp_ddl.sql first - that file is where the schema is",
        "-- designed and explained; this one just fills it.",
        "-- Do not hand-edit. Regenerate instead, so every page's numbers stay in sync.",
        "",
    ]
    for name, rows in tables.items():
        parts.append(insert_block(name, rows))
        parts.append("")
    body = "\n".join(parts)
    (SQL / "02_seed.sql").write_text(body + "\n")
    return body


def write_browser_seed(tables: dict[str, list]) -> None:
    """assets/bazaar-seed.js - window.BAZAAR_SEED, the OLTP source in a browser tab."""
    ASSETS.mkdir(exist_ok=True)
    # single source of truth for the schema: the hand-written, commented DDL file
    ddl = (SQL / "01_oltp_ddl.sql").read_text()
    parts = [ddl.strip(), ""]
    for name, rows in tables.items():
        parts.append(insert_block(name, rows))
        parts.append("")
    sql_text = "\n".join(parts).replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    js = (
        "/* bazaar-seed.js - the Bazaar marketplace OLTP source, in your browser.\n"
        "   Generated by python/gen_bazaar_data.py (seed 42). Every live lab on this site\n"
        "   seeds a fresh copy before running your SQL, so nothing you type breaks the next\n"
        "   example. Star-schema tables are NOT here on purpose: you build them from this\n"
        "   source with assets/bazaar-star.js (sql/10-12), exactly as a real load would. */\n\n"
        "window.BAZAAR_SEED = `\n" + sql_text + "`;\n"
    )
    (ASSETS / "bazaar-seed.js").write_text(js)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", action="store_true", help="print row counts")
    args = ap.parse_args()

    tables = generate()
    write_csvs(tables)
    write_sql_seed(tables)
    write_browser_seed(tables)

    print(f"Bazaar source generated - {START} to {END}, seed {SEED}")
    if args.rows:
        for name, rows in tables.items():
            print(f"  {name:<14} {len(rows):>6} rows")
    print(f"  CSVs      -> {DATA.relative_to(ROOT)}/")
    print(f"  SQL seed  -> sql/02_seed.sql")
    print(f"  Browser   -> assets/bazaar-seed.js")


if __name__ == "__main__":
    main()
