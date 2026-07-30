-- ============================================================================
-- 01_oltp_ddl.sql - Bazaar's OLTP source schema (sessions b3-b4)
--
-- Eight tables, third normal form, written the way an application database
-- should be written: every fact stored once, every relationship enforced by a
-- foreign key, every column a single value. This is NOT the shape analysts
-- query - that is the star schema in 10/11. This is the shape that keeps the
-- application correct while people are buying things.
--
-- Design decisions worth reading (each maps to a session):
--   b3  users:orders is 1:many. carts:products is many:many, resolved by the
--       cart_items associative table. orders:order_items is the classic
--       header/line pair - the line table exists because one order holds many
--       products, so the quantity cannot live on the order.
--   b4  Keys: merchant_id is a NATURAL key (M07 is meaningful, stable, printed
--       on invoices). user_id / order_id are SURROGATE integers, because email
--       changes and nothing outside the system owns an order number.
--       cart_items and order_items use COMPOSITE primary keys - the grain of
--       the row is the pair, not either half.
--   b5  Types + constraints: money is REAL here for portability (a production
--       system uses NUMERIC/DECIMAL - never floats for money at scale, see the
--       note at the bottom). CHECK constraints stop negative quantities at the
--       door instead of in a dashboard three months later.
--   b7  Time: every timestamp is stored as an ISO-8601 string in UTC and named
--       *_ts. Dates that are genuinely dates (joined_date, launched_date) are
--       named *_date. The naming carries the grain so nobody has to guess.
--
-- Engine: SQLite / sql.js (the live labs on the course site). It runs on DuckDB
-- and Postgres too, with the type note at the bottom applied.
-- ============================================================================

DROP TABLE IF EXISTS transactions;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS cart_items;
DROP TABLE IF EXISTS carts;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS merchants;
DROP TABLE IF EXISTS users;

-- ---------------------------------------------------------------- people
-- One row per registered shopper. is_guest marks checkout-without-account,
-- which matters later: guests have no history, so any "returning customer"
-- metric has to exclude them or admit it counts them wrong.
CREATE TABLE users (
  user_id             INTEGER PRIMARY KEY,
  email               TEXT NOT NULL UNIQUE,
  signup_ts           TEXT NOT NULL,
  country             TEXT NOT NULL,
  city                TEXT,
  acquisition_channel TEXT,
  is_guest            INTEGER NOT NULL DEFAULT 0 CHECK (is_guest IN (0, 1))
);

-- ---------------------------------------------------------------- the marketplace side
-- One row per selling merchant. commission_pct is what Bazaar keeps - it is an
-- attribute that CHANGES over time, which is exactly why dim_merchant gets
-- slowly-changing-dimension treatment in session b6.
CREATE TABLE merchants (
  merchant_id     TEXT PRIMARY KEY,
  merchant_name   TEXT NOT NULL,
  category        TEXT NOT NULL,
  country         TEXT NOT NULL,
  tier            TEXT NOT NULL CHECK (tier IN ('bronze', 'silver', 'gold', 'platinum')),
  commission_pct  REAL NOT NULL CHECK (commission_pct BETWEEN 0 AND 1),
  joined_date     TEXT NOT NULL
);

-- One row per sellable product, owned by exactly one merchant.
-- status is operational state ('active' / 'out_of_stock'), not a category -
-- session b8 uses it to explain half of a revenue drop.
CREATE TABLE products (
  product_id    INTEGER PRIMARY KEY,
  merchant_id   TEXT NOT NULL REFERENCES merchants(merchant_id),
  sku           TEXT NOT NULL UNIQUE,
  product_name  TEXT NOT NULL,
  category      TEXT NOT NULL,
  list_price    REAL NOT NULL CHECK (list_price > 0),
  unit_cost     REAL NOT NULL CHECK (unit_cost >= 0),
  launched_date TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'active'
);

-- ---------------------------------------------------------------- intent
-- A cart is intent, not money. Most carts never become orders, and that gap is
-- a metric the business cares about - so the cart is a first-class table, not
-- a session variable thrown away at checkout.
CREATE TABLE carts (
  cart_id     INTEGER PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(user_id),
  created_ts  TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('active', 'abandoned', 'converted'))
);

-- Associative table resolving the many:many between carts and products.
-- The composite PK says the grain out loud: one row per product per cart.
CREATE TABLE cart_items (
  cart_id     INTEGER NOT NULL REFERENCES carts(cart_id),
  product_id  INTEGER NOT NULL REFERENCES products(product_id),
  quantity    INTEGER NOT NULL CHECK (quantity > 0),
  added_ts    TEXT NOT NULL,
  PRIMARY KEY (cart_id, product_id)
);

-- ---------------------------------------------------------------- money
-- The order header: who, when, where it ships. No amounts live here on
-- purpose. An order total is derivable from its lines, and a stored total that
-- disagrees with its lines is the single most common data-quality bug in
-- ecommerce. Derive it, or store it as an explicitly reconciled snapshot -
-- never as a casually maintained copy.
CREATE TABLE orders (
  order_id      INTEGER PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES users(user_id),
  cart_id       INTEGER REFERENCES carts(cart_id),
  order_ts      TEXT NOT NULL,
  status        TEXT NOT NULL,
  ship_country  TEXT NOT NULL,
  currency      TEXT NOT NULL DEFAULT 'SGD'
);

-- The order line: the true grain of "what was sold".
-- merchant_id is denormalized here from products ON PURPOSE - it is the
-- merchant at time of sale, and a product can be transferred between merchants
-- later. This is a point-in-time capture, not redundancy. Session b3 explains
-- the difference and why the anomaly lab does not flag it.
CREATE TABLE order_items (
  order_id      INTEGER NOT NULL REFERENCES orders(order_id),
  line_no       INTEGER NOT NULL,
  product_id    INTEGER NOT NULL REFERENCES products(product_id),
  merchant_id   TEXT NOT NULL REFERENCES merchants(merchant_id),
  quantity      INTEGER NOT NULL CHECK (quantity > 0),
  unit_price    REAL NOT NULL CHECK (unit_price >= 0),
  discount_amt  REAL NOT NULL DEFAULT 0 CHECK (discount_amt >= 0),
  PRIMARY KEY (order_id, line_no)
);

-- One row per payment ATTEMPT, not per order. An order can have a decline, a
-- retry that succeeds, and a refund later - three rows, one order. This is the
-- table that makes "why did sales drop" answerable, and the table that makes
-- naive revenue queries double-count. Sessions b7 and b9 both turn on it.
CREATE TABLE transactions (
  txn_id          INTEGER PRIMARY KEY,
  order_id        INTEGER NOT NULL REFERENCES orders(order_id),
  txn_ts          TEXT NOT NULL,
  amount          REAL NOT NULL,              -- negative for refunds
  currency        TEXT NOT NULL DEFAULT 'SGD',
  payment_method  TEXT NOT NULL,
  status          TEXT NOT NULL CHECK (status IN ('approved', 'declined', 'refunded')),
  decline_reason  TEXT,                        -- NULL unless status = 'declined'
  psp_ref         TEXT NOT NULL UNIQUE         -- the payment provider's own id
);

-- ---------------------------------------------------------------- physical layer
-- Indexes follow the access paths the application actually uses: look up an
-- order by user, a line by product or merchant, a payment by order, anything
-- by time. Every index costs write throughput, so this list is short by design
-- (session b5).
CREATE INDEX idx_orders_ts        ON orders(order_ts);
CREATE INDEX idx_orders_user      ON orders(user_id);
CREATE INDEX idx_oi_product       ON order_items(product_id);
CREATE INDEX idx_oi_merchant      ON order_items(merchant_id);
CREATE INDEX idx_txn_order        ON transactions(order_id);
CREATE INDEX idx_txn_ts           ON transactions(txn_ts);
CREATE INDEX idx_cart_items_prod  ON cart_items(product_id);

-- ============================================================================
-- Portability note (session b5, and read this before you ship anything real):
--   money  : REAL here so the browser labs run everywhere. In production use
--            NUMERIC(12,2) / DECIMAL - binary floats cannot represent 0.10 and
--            your ledger will drift by cents at volume.
--   time   : TEXT ISO-8601 UTC here (SQLite has no native timestamp type).
--            In Postgres/DuckDB use TIMESTAMP WITH TIME ZONE and store UTC.
--   ids    : INTEGER PRIMARY KEY here. In Postgres use GENERATED ALWAYS AS
--            IDENTITY; in a distributed writer use UUIDv7 so ids stay sortable.
--   FKs    : SQLite only enforces them after PRAGMA foreign_keys = ON. A
--            constraint you declared but did not enable is a comment, not a
--            constraint - session b4's favourite trap.
-- ============================================================================
