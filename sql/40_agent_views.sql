-- ============================================================================
-- 40_agent_views.sql - the model an AI agent is allowed to see (session b9)
--
-- Text-to-SQL fails for boring reasons, and almost all of them are modeling
-- reasons: cryptic column names, two tables that look joinable but are not,
-- metrics with no single definition, and grains nobody wrote down. So the agent
-- does not get the star. It gets this narrow, flattened, self-describing layer.
--
-- Five design rules, each one a failure this prevents:
--
--   1. ONE ROW MEANS ONE SENTENCE. Every view below has its grain in its
--      comment and in the view name. v_sales_line is one product line on one
--      order. No agent can hold "it depends" in its head, and neither can a
--      new analyst.
--
--   2. NO EXPOSED FACT-TO-FACT PATH. The two facts are never both reachable in
--      one view, so the agent physically cannot write the join that
--      double-counts revenue. Removing the footgun beats prompting the agent
--      not to pull the trigger.
--
--   3. NAMES ARE THE PROMPT. net_revenue, not amt2. merchant_name, not m_nm.
--      is_declined, not flag3. The schema is the largest part of the context an
--      agent reads - every unclear name spends tokens and buys a wrong guess.
--
--   4. NO RATIOS, EVER. Rates ship as numerator + denominator so the agent
--      divides at the right grain instead of averaging averages. The one place
--      ratios are allowed to exist is a human's SELECT list.
--
--   5. METRICS ARE DATA. v_metric_definitions puts the definition of every
--      metric IN the database, so the agent can look up "what is AOV here"
--      instead of inventing it. This is the smallest useful semantic layer, and
--      it is the single highest-leverage thing in this file.
--
-- Run after 20_marts.sql.
-- ============================================================================

DROP VIEW IF EXISTS v_sales_line;
DROP VIEW IF EXISTS v_payment_attempt;
DROP VIEW IF EXISTS v_cart;
DROP VIEW IF EXISTS v_merchant_day;
DROP VIEW IF EXISTS v_hour_of_day;
DROP TABLE IF EXISTS v_metric_definitions;

-- ---------------------------------------------------------------------------
-- v_sales_line
-- GRAIN: one row per product line on one order.
-- USE FOR: anything about what was sold - revenue, units, margin, by merchant,
--          product, category, price tier, user, date, hour.
-- DO NOT USE FOR: payments (declines, refunds) or demand (carts). Different
--          grains live in v_payment_attempt and v_cart.
-- ---------------------------------------------------------------------------
CREATE VIEW v_sales_line AS
SELECT
  d.full_date            AS order_date,
  d.year                 AS order_year,
  d.month_name           AS order_month_name,
  d.day_name             AS order_day_name,
  d.is_weekend           AS is_weekend,
  t.hour_24              AS order_hour,
  t.hour_label           AS order_hour_label,
  t.daypart              AS order_daypart,
  m.merchant_id          AS merchant_id,
  m.merchant_name        AS merchant_name,
  m.category             AS merchant_category,
  m.tier                 AS merchant_tier,
  p.product_id           AS product_id,
  p.product_name         AS product_name,
  p.category             AS product_category,
  p.price_tier           AS product_price_tier,
  p.status               AS product_status,
  u.user_id              AS user_id,
  u.country              AS user_country,
  u.city                 AS user_city,
  u.acquisition_channel  AS user_acquisition_channel,
  u.tenure_bucket        AS user_tenure_bucket,
  f.order_id             AS order_id,
  f.line_no              AS line_no,
  f.quantity             AS units,
  f.gross_amount         AS gross_revenue,
  f.discount_amount      AS discount,
  f.net_amount           AS net_revenue,      -- the revenue measure. Sum this one.
  f.commission_amount    AS commission,
  f.margin_amount        AS margin,
  f.is_paid              AS is_paid           -- 1 = payment settled. Filter on this for money questions.
FROM fact_order_item f
JOIN dim_date d        ON d.date_key = f.date_key
JOIN dim_time_of_day t ON t.time_key = f.time_key
JOIN dim_merchant m    ON m.merchant_sk = f.merchant_sk
JOIN dim_product p     ON p.product_sk = f.product_sk
JOIN dim_user u        ON u.user_sk = f.user_sk;

-- ---------------------------------------------------------------------------
-- v_payment_attempt
-- GRAIN: one row per payment attempt (an order can have several).
-- USE FOR: approvals, declines, refunds, decline reasons, settled money,
--          payment method performance, peak transaction hours.
-- DO NOT USE FOR: revenue by product or merchant - an attempt has no product.
--          Use v_sales_line for that.
-- ---------------------------------------------------------------------------
CREATE VIEW v_payment_attempt AS
SELECT
  d.full_date        AS attempt_date,
  d.day_name         AS attempt_day_name,
  d.is_weekend       AS is_weekend,
  t.hour_24          AS attempt_hour,
  t.hour_label       AS attempt_hour_label,
  t.daypart          AS attempt_daypart,
  pm.payment_method  AS payment_method,
  pm.method_label    AS payment_method_label,
  pm.method_family   AS payment_method_family,
  u.user_id          AS user_id,
  u.country          AS user_country,
  f.order_id         AS order_id,
  f.txn_id           AS txn_id,
  f.amount           AS attempt_amount,      -- signed: negative = refund
  f.approved_amount  AS approved_amount,     -- additive
  f.declined_amount  AS declined_amount,     -- additive
  f.is_approved      AS is_approved,         -- sum for the numerator
  f.is_declined      AS is_declined,         -- sum for the numerator
  f.is_refund        AS is_refund,
  f.decline_reason   AS decline_reason
FROM fact_transaction f
JOIN dim_date d            ON d.date_key = f.date_key
JOIN dim_time_of_day t     ON t.time_key = f.time_key
JOIN dim_payment_method pm ON pm.payment_method_key = f.payment_method_key
JOIN dim_user u            ON u.user_sk = f.user_sk;

-- ---------------------------------------------------------------------------
-- v_cart
-- GRAIN: one row per cart.
-- USE FOR: demand, abandonment, conversion rate, abandoned value.
-- NOTE: cart_value is LIST value of the contents, not revenue. A converted cart
--       and its order will not match to the cent, because orders carry discounts.
--       That mismatch is real and documented, not a bug to "fix" by joining.
-- ---------------------------------------------------------------------------
CREATE VIEW v_cart AS
SELECT
  d.full_date        AS cart_date,
  d.day_name         AS cart_day_name,
  t.hour_24          AS cart_hour,
  t.daypart          AS cart_daypart,
  m.merchant_id      AS dominant_merchant_id,
  m.merchant_name    AS dominant_merchant_name,
  u.user_id          AS user_id,
  u.acquisition_channel AS user_acquisition_channel,
  f.cart_id          AS cart_id,
  f.order_id         AS order_id,            -- NULL when abandoned
  f.items_count      AS distinct_products,
  f.units_count      AS units,
  f.cart_value       AS cart_value,
  f.converted_flag   AS is_converted,        -- sum for the numerator
  f.abandoned_value  AS abandoned_value,
  f.minutes_to_order AS minutes_to_order
FROM fact_cart f
JOIN dim_date d        ON d.date_key = f.date_key
JOIN dim_time_of_day t ON t.time_key = f.time_key
JOIN dim_merchant m    ON m.merchant_sk = f.merchant_sk
JOIN dim_user u        ON u.user_sk = f.user_sk;

-- ---------------------------------------------------------------------------
-- v_merchant_day / v_hour_of_day - the two pre-aggregated views, for questions
-- that are always asked at those grains. Cheap for the agent: fewer rows, fewer
-- joins, no chance of a fan-out.
-- ---------------------------------------------------------------------------
CREATE VIEW v_merchant_day AS
SELECT
  activity_date      AS activity_date,
  merchant_id        AS merchant_id,
  merchant_name      AS merchant_name,
  merchant_category  AS merchant_category,
  merchant_tier      AS merchant_tier,
  orders             AS orders,
  units              AS units,
  net_revenue        AS net_revenue,
  commission         AS commission,
  margin             AS margin,
  aov_numerator      AS aov_numerator,       -- divide these two for AOV
  aov_denominator    AS aov_denominator
FROM mart_merchant_daily;

CREATE VIEW v_hour_of_day AS
SELECT
  hour_24            AS hour_24,
  hour_label         AS hour_label,
  daypart            AS daypart,
  is_weekend         AS is_weekend,
  SUM(attempts)      AS attempts,
  SUM(approvals)     AS approvals,
  SUM(declines)      AS declines,
  SUM(approved_amount) AS approved_amount
FROM mart_hourly_transactions
GROUP BY hour_24, hour_label, daypart, is_weekend;

-- ---------------------------------------------------------------------------
-- v_metric_definitions - the semantic layer, as data.
-- The agent reads this table before writing SQL. So do humans. When someone
-- asks "is revenue gross or net here", the answer is a row, not a Slack thread.
-- Keep it in the database rather than only in a YAML file so it can never drift
-- out of sync with what is queryable.
-- ---------------------------------------------------------------------------
CREATE TABLE v_metric_definitions (
  metric_name    TEXT PRIMARY KEY,
  definition     TEXT NOT NULL,
  sql_expression TEXT NOT NULL,
  source_view    TEXT NOT NULL,
  grain          TEXT NOT NULL,
  caveat         TEXT NOT NULL
);

INSERT INTO v_metric_definitions VALUES
 ('net_revenue',
  'Money charged for goods after line discounts, excluding failed payments.',
  'SUM(net_revenue) WHERE is_paid = 1',
  'v_sales_line', 'order line',
  'Excludes refunds. For settled cash including refunds use settled_amount.'),

 ('gross_revenue',
  'Money charged before discounts.',
  'SUM(gross_revenue) WHERE is_paid = 1',
  'v_sales_line', 'order line',
  'Almost never the number a business person means by "revenue". Ask first.'),

 ('orders',
  'Count of distinct orders that settled.',
  'COUNT(DISTINCT order_id) WHERE is_paid = 1',
  'v_sales_line', 'order line',
  'COUNT(*) counts LINES, not orders. This is the most common agent error.'),

 ('aov',
  'Average order value: settled revenue divided by settled orders.',
  'SUM(net_revenue) / COUNT(DISTINCT order_id) WHERE is_paid = 1',
  'v_sales_line', 'order line',
  'Never average an AOV. Recompute from the two sums at the grain you need.'),

 ('units',
  'Quantity of items sold.',
  'SUM(units) WHERE is_paid = 1',
  'v_sales_line', 'order line', 'None.'),

 ('margin',
  'Net revenue minus product cost.',
  'SUM(margin) WHERE is_paid = 1',
  'v_sales_line', 'order line',
  'Cost is standard unit cost, not landed cost. Not a finance-grade margin.'),

 ('commission',
  'Marketplace take, at the commission rate in force at time of sale.',
  'SUM(commission) WHERE is_paid = 1',
  'v_sales_line', 'order line',
  'Uses the SCD2 merchant version on the fact, so historic rates stay correct.'),

 ('decline_rate',
  'Share of payment attempts that were declined.',
  'SUM(is_declined) * 1.0 / COUNT(*)',
  'v_payment_attempt', 'payment attempt',
  'Always report the attempt count beside it. Below ~30 attempts it is noise.'),

 ('approval_rate',
  'Share of payment attempts that were approved.',
  'SUM(is_approved) * 1.0 / COUNT(*)',
  'v_payment_attempt', 'payment attempt', 'Same small-sample caveat as decline_rate.'),

 ('settled_amount',
  'Cash that actually moved, refunds netted off.',
  'SUM(attempt_amount) WHERE is_approved = 1 OR is_refund = 1',
  'v_payment_attempt', 'payment attempt',
  'Differs from net_revenue: refund timing and retries. Reconcile, do not assume.'),

 ('cart_conversion_rate',
  'Share of carts that became an order.',
  'SUM(is_converted) * 1.0 / COUNT(*)',
  'v_cart', 'cart',
  'Carts, not sessions. A user with three carts counts three times.'),

 ('abandoned_value',
  'List value sitting in carts that never converted.',
  'SUM(abandoned_value)',
  'v_cart', 'cart',
  'List value, not lost revenue - most of it would never have converted.'),

 ('peak_hour',
  'The hour of day with the most payment attempts.',
  'ORDER BY SUM(attempts) DESC LIMIT 1',
  'v_hour_of_day', 'hour of day',
  'Split weekday/weekend before acting on it - the peaks differ.');

-- ============================================================================
-- Two rules for whoever wires this to a model (session b9 tests both):
--   * Read-only credentials. Views only, no base tables, no writes.
--   * Show the generated SQL to the user before the number. A confident wrong
--     answer with no SQL is worse than no answer, and the SQL is the only part
--     a human can actually check.
-- ============================================================================
