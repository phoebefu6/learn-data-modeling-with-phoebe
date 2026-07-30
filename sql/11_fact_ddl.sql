-- ============================================================================
-- 11_fact_ddl.sql - Bazaar's facts (session b7)
--
-- Three facts, three grains, three different questions. Getting the grain
-- sentence right is 80% of fact design, so each table below opens with its
-- grain stated as one sentence. If you cannot write that sentence, you do not
-- have a fact table yet - you have a query result you are about to freeze.
--
--   fact_order_item   one row per product line on an order   -> what was sold
--   fact_transaction  one row per payment attempt            -> what was paid
--   fact_cart         one row per cart                       -> what was wanted
--
-- Why three and not one big table: they have genuinely different grains and
-- they do not divide evenly into each other. One order can have three payment
-- attempts and four lines; forcing them into one table produces 12 rows and a
-- revenue number that is wrong by 3x. The double-count trap in session b9 is
-- exactly a query that joins two of these facts directly - which you never do.
-- Facts join to each other only THROUGH a shared dimension (conformed
-- dimensions), or by aggregating each to a common grain first.
--
-- Measure discipline used below:
--   additive      - safe to SUM across every dimension (net_amount, quantity)
--   semi-additive - safe to SUM across some dims but not time (none here; a
--                   stock level or account balance is the classic case)
--   non-additive  - never SUM, always recompute from parts (any ratio:
--                   decline_rate, conversion_rate, AOV). Ratios are stored as
--                   their NUMERATOR and DENOMINATOR, never as the ratio.
--   degenerate    - an identifier kept on the fact with no dimension of its
--                   own (order_id, txn_id, cart_id). Useful for drill-down and
--                   for counting distinct orders.
-- ============================================================================

DROP TABLE IF EXISTS fact_order_item;
DROP TABLE IF EXISTS fact_transaction;
DROP TABLE IF EXISTS fact_cart;

-- ---------------------------------------------------------------- fact_order_item
-- GRAIN: one row per product line on one order.
-- This is the revenue fact. Every "sales by X" question resolves here.
CREATE TABLE fact_order_item (
  order_item_sk    INTEGER PRIMARY KEY,

  -- dimension foreign keys (the "by what" side)
  date_key         INTEGER NOT NULL REFERENCES dim_date(date_key),
  time_key         INTEGER NOT NULL REFERENCES dim_time_of_day(time_key),
  user_sk          INTEGER NOT NULL REFERENCES dim_user(user_sk),
  merchant_sk      INTEGER NOT NULL REFERENCES dim_merchant(merchant_sk),
  product_sk       INTEGER NOT NULL REFERENCES dim_product(product_sk),

  -- degenerate dimensions: identifiers with no dimension table of their own
  order_id         INTEGER NOT NULL,
  line_no          INTEGER NOT NULL,

  -- additive measures
  quantity         INTEGER NOT NULL,
  unit_price       REAL NOT NULL,       -- NOT additive: it is a rate. Kept for reference.
  gross_amount     REAL NOT NULL,       -- quantity * unit_price
  discount_amount  REAL NOT NULL,
  net_amount       REAL NOT NULL,       -- gross - discount  <- the revenue measure
  commission_amount REAL NOT NULL,      -- net * commission_pct at time of sale
  cost_amount      REAL NOT NULL,       -- quantity * unit_cost, for margin
  margin_amount    REAL NOT NULL,       -- net - cost

  -- a flag stored as 0/1 so it can be SUMmed into a count
  is_paid          INTEGER NOT NULL CHECK (is_paid IN (0, 1)),

  UNIQUE (order_id, line_no)            -- the grain, enforced
);
CREATE INDEX idx_foi_date     ON fact_order_item(date_key);
CREATE INDEX idx_foi_merchant ON fact_order_item(merchant_sk);
CREATE INDEX idx_foi_product  ON fact_order_item(product_sk);

-- ---------------------------------------------------------------- fact_transaction
-- GRAIN: one row per payment attempt.
-- Approvals, declines and refunds all live here. amount is signed: refunds are
-- negative, so SUM(amount) over approved+refunded is net settled money.
-- decline_reason stays on the fact as a low-cardinality attribute rather than
-- getting its own dimension - a judgement call session b7 argues both ways.
CREATE TABLE fact_transaction (
  txn_sk             INTEGER PRIMARY KEY,

  date_key           INTEGER NOT NULL REFERENCES dim_date(date_key),
  time_key           INTEGER NOT NULL REFERENCES dim_time_of_day(time_key),
  user_sk            INTEGER NOT NULL REFERENCES dim_user(user_sk),
  payment_method_key INTEGER NOT NULL REFERENCES dim_payment_method(payment_method_key),

  txn_id             INTEGER NOT NULL,   -- degenerate
  order_id           INTEGER NOT NULL,   -- degenerate, the drill-down path

  amount             REAL NOT NULL,      -- signed: negative = refund
  is_approved        INTEGER NOT NULL CHECK (is_approved IN (0, 1)),
  is_declined        INTEGER NOT NULL CHECK (is_declined IN (0, 1)),
  is_refund          INTEGER NOT NULL CHECK (is_refund IN (0, 1)),
  approved_amount    REAL NOT NULL,      -- amount when approved, else 0 - additive
  declined_amount    REAL NOT NULL,      -- amount when declined, else 0 - additive
  decline_reason     TEXT NOT NULL DEFAULT 'none',

  UNIQUE (txn_id)
);
CREATE INDEX idx_ftx_date  ON fact_transaction(date_key);
CREATE INDEX idx_ftx_order ON fact_transaction(order_id);

-- ---------------------------------------------------------------- fact_cart
-- GRAIN: one row per cart.
-- A cart that never converted has no money attached, which is the point: this
-- is where demand that did NOT become revenue is recorded. Without it, "sales
-- dropped" and "people stopped wanting to buy" look identical.
-- converted_flag + cart_value are the numerator/denominator pair behind
-- conversion rate and abandoned value - the ratio itself is never stored.
CREATE TABLE fact_cart (
  cart_sk         INTEGER PRIMARY KEY,

  date_key        INTEGER NOT NULL REFERENCES dim_date(date_key),
  time_key        INTEGER NOT NULL REFERENCES dim_time_of_day(time_key),
  user_sk         INTEGER NOT NULL REFERENCES dim_user(user_sk),
  merchant_sk     INTEGER NOT NULL REFERENCES dim_merchant(merchant_sk),  -- cart's dominant merchant

  cart_id         INTEGER NOT NULL,   -- degenerate
  order_id        INTEGER,            -- NULL when abandoned - the only nullable FK-ish column,
                                      -- and it is a degenerate id, not a dimension key

  items_count     INTEGER NOT NULL,
  units_count     INTEGER NOT NULL,
  cart_value      REAL NOT NULL,      -- list value of what was in it
  converted_flag  INTEGER NOT NULL CHECK (converted_flag IN (0, 1)),
  abandoned_value REAL NOT NULL,      -- cart_value when not converted, else 0 - additive
  minutes_to_order REAL,              -- NULL when abandoned

  UNIQUE (cart_id)
);
CREATE INDEX idx_fcart_date     ON fact_cart(date_key);
CREATE INDEX idx_fcart_merchant ON fact_cart(merchant_sk);

-- ============================================================================
-- The two questions to ask of any fact table you are handed:
--   1. What is one row? If the answer needs the word "and", you have two facts.
--   2. Can I SUM every measure across every dimension? Any column that fails
--      is a ratio in disguise - split it into numerator and denominator.
-- ============================================================================
