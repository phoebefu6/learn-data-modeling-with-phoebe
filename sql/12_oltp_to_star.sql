-- ============================================================================
-- 12_oltp_to_star.sql - load the star from the OLTP source (sessions b6-b7)
--
-- Run order: 01_oltp_ddl -> 02_seed -> 10_dim_ddl -> 11_fact_ddl -> this file.
-- Dimensions load first, because facts look up their surrogate keys.
--
-- This is a full-refresh load, deliberately: it keeps the modeling visible
-- instead of burying it in merge logic. Incremental loads, MERGE statements and
-- type-2 change application are the sibling course learn-data-warehouse
-- (builder sessions 4-6) - that is a loading concern, this is a modeling one.
--
-- Every INSERT below is one modeling decision made concrete. Read the comment
-- above each one before you read the SQL.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- dim_date - generated, never sourced. Recursive CTE walks the calendar so the
-- dimension covers the whole data range plus headroom. The 'unknown' member
-- (key -1) exists so a fact with a broken date still joins instead of vanishing.
-- ---------------------------------------------------------------------------
INSERT INTO dim_date (date_key, full_date, year, quarter, month, month_name,
                      day_of_month, day_of_week, day_name, week_of_year, is_weekend)
VALUES (-1, '1900-01-01', 1900, 1, 1, 'unknown', 1, 0, 'unknown', 1, 0);

WITH RECURSIVE cal(d) AS (
  SELECT date('2026-03-01')
  UNION ALL
  SELECT date(d, '+1 day') FROM cal WHERE d < date('2026-09-30')
)
INSERT INTO dim_date (date_key, full_date, year, quarter, month, month_name,
                      day_of_month, day_of_week, day_name, week_of_year, is_weekend)
SELECT
  CAST(strftime('%Y%m%d', d) AS INTEGER),
  d,
  CAST(strftime('%Y', d) AS INTEGER),
  (CAST(strftime('%m', d) AS INTEGER) + 2) / 3,
  CAST(strftime('%m', d) AS INTEGER),
  CASE strftime('%m', d)
    WHEN '01' THEN 'January'  WHEN '02' THEN 'February' WHEN '03' THEN 'March'
    WHEN '04' THEN 'April'    WHEN '05' THEN 'May'      WHEN '06' THEN 'June'
    WHEN '07' THEN 'July'     WHEN '08' THEN 'August'   WHEN '09' THEN 'September'
    WHEN '10' THEN 'October'  WHEN '11' THEN 'November' ELSE 'December' END,
  CAST(strftime('%d', d) AS INTEGER),
  CAST(strftime('%w', d) AS INTEGER),
  CASE strftime('%w', d)
    WHEN '0' THEN 'Sunday'   WHEN '1' THEN 'Monday'  WHEN '2' THEN 'Tuesday'
    WHEN '3' THEN 'Wednesday' WHEN '4' THEN 'Thursday' WHEN '5' THEN 'Friday'
    ELSE 'Saturday' END,
  CAST(strftime('%W', d) AS INTEGER),
  CASE WHEN strftime('%w', d) IN ('0', '6') THEN 1 ELSE 0 END
FROM cal;

-- ---------------------------------------------------------------------------
-- dim_time_of_day - 24 rows, generated. daypart is the business vocabulary;
-- hour_24 is the machine one. Both, because the agent in b9 needs the label and
-- the analyst needs the number.
-- ---------------------------------------------------------------------------
WITH RECURSIVE h(n) AS (
  SELECT 0 UNION ALL SELECT n + 1 FROM h WHERE n < 23
)
INSERT INTO dim_time_of_day (time_key, hour_24, hour_label, daypart, is_business_hour)
SELECT
  n, n,
  printf('%02d:00-%02d:59', n, n),
  CASE WHEN n < 6 THEN 'overnight'
       WHEN n < 11 THEN 'morning'
       WHEN n < 14 THEN 'lunch'
       WHEN n < 18 THEN 'afternoon'
       WHEN n < 23 THEN 'evening'
       ELSE 'late' END,
  CASE WHEN n BETWEEN 9 AND 18 THEN 1 ELSE 0 END
FROM h;

-- ---------------------------------------------------------------------------
-- dim_user - SCD type 1. tenure_bucket is computed ONCE here so every report
-- bands tenure identically. COALESCE guards every attribute: 'unknown', never
-- NULL (rule 4 in 10_dim_ddl).
-- ---------------------------------------------------------------------------
INSERT INTO dim_user (user_sk, user_id, country, city, acquisition_channel,
                      signup_date, tenure_bucket, is_guest)
VALUES (-1, -1, 'unknown', 'unknown', 'unknown', NULL, 'unknown', 0);

INSERT INTO dim_user (user_id, country, city, acquisition_channel,
                      signup_date, tenure_bucket, is_guest)
SELECT
  u.user_id,
  COALESCE(u.country, 'unknown'),
  COALESCE(u.city, 'unknown'),
  COALESCE(u.acquisition_channel, 'unknown'),
  date(u.signup_ts),
  CASE
    WHEN julianday('2026-06-29') - julianday(u.signup_ts) < 90  THEN 'new'
    WHEN julianday('2026-06-29') - julianday(u.signup_ts) < 365 THEN '3-12m'
    ELSE '1y+'
  END,
  u.is_guest
FROM users u;

-- ---------------------------------------------------------------------------
-- dim_merchant - SCD type 2 structure, loaded with one (current) version each.
-- valid_from is the merchant's joined_date, so the version genuinely covers the
-- period the facts fall in. When tier or commission_pct changes tomorrow, the
-- loader closes this row (valid_to = yesterday, is_current = 0) and inserts a
-- new one - and every historic fact keeps pointing at this merchant_sk.
-- ---------------------------------------------------------------------------
INSERT INTO dim_merchant (merchant_sk, merchant_id, merchant_name, category, country,
                          tier, commission_pct, joined_date, valid_from, valid_to, is_current)
VALUES (-1, 'UNK', 'unknown', 'unknown', 'unknown', 'unknown', 0, NULL, '1900-01-01', '9999-12-31', 1);

INSERT INTO dim_merchant (merchant_id, merchant_name, category, country,
                          tier, commission_pct, joined_date, valid_from, valid_to, is_current)
SELECT m.merchant_id, m.merchant_name, m.category, m.country,
       m.tier, m.commission_pct, m.joined_date, m.joined_date, '9999-12-31', 1
FROM merchants m;

-- ---------------------------------------------------------------------------
-- dim_product - SCD type 2 structure, flattened with its merchant's name.
-- price_tier is modeled here, not in the source: budget / mid / premium is a
-- business band, and defining it once in the dimension is what stops three
-- dashboards from disagreeing about what "premium" means.
-- ---------------------------------------------------------------------------
INSERT INTO dim_product (product_sk, product_id, sku, product_name, category, merchant_id,
                         merchant_name, list_price, unit_cost, price_tier, status,
                         launched_date, valid_from, valid_to, is_current)
VALUES (-1, -1, 'UNK', 'unknown', 'unknown', 'UNK', 'unknown', 0, 0, 'unknown', 'unknown',
        NULL, '1900-01-01', '9999-12-31', 1);

INSERT INTO dim_product (product_id, sku, product_name, category, merchant_id, merchant_name,
                         list_price, unit_cost, price_tier, status, launched_date,
                         valid_from, valid_to, is_current)
SELECT
  p.product_id, p.sku, p.product_name, p.category, p.merchant_id, m.merchant_name,
  p.list_price, p.unit_cost,
  CASE WHEN p.list_price < 25 THEN 'budget'
       WHEN p.list_price < 80 THEN 'mid'
       ELSE 'premium' END,
  p.status, p.launched_date,
  p.launched_date, '9999-12-31', 1
FROM products p
JOIN merchants m ON m.merchant_id = p.merchant_id;

-- ---------------------------------------------------------------------------
-- dim_payment_method - built from the distinct source values, with the business
-- grouping attached. If a new method appears in the source and nobody adds it
-- here, the fact load points it at key -1 and the row is still counted. That is
-- the whole reason the unknown member exists.
-- ---------------------------------------------------------------------------
INSERT INTO dim_payment_method (payment_method_key, payment_method, method_label, method_family, is_card)
VALUES
  (-1, 'unknown',         'Unknown',        'unknown', 0),
  (1,  'card_visa',       'Visa',           'card',    1),
  (2,  'card_mastercard', 'Mastercard',     'card',    1),
  (3,  'card_amex',       'Amex',           'card',    1),
  (4,  'paynow',          'PayNow',         'bank',    0),
  (5,  'grabpay',         'GrabPay',        'wallet',  0),
  (6,  'bank_transfer',   'Bank transfer',  'bank',    0);

-- ---------------------------------------------------------------------------
-- fact_order_item - the revenue fact.
-- Every dimension key is resolved by LEFT JOIN + COALESCE to -1. Never an inner
-- join: an inner join silently drops the fact row when a dimension lookup
-- misses, and silently-missing revenue is the worst failure mode in this whole
-- course. Money is computed once, here, so no downstream query re-derives it.
-- ---------------------------------------------------------------------------
INSERT INTO fact_order_item (
  date_key, time_key, user_sk, merchant_sk, product_sk,
  order_id, line_no, quantity, unit_price, gross_amount, discount_amount,
  net_amount, commission_amount, cost_amount, margin_amount, is_paid)
SELECT
  COALESCE(dd.date_key, -1),
  COALESCE(CAST(strftime('%H', o.order_ts) AS INTEGER), 0),
  COALESCE(du.user_sk, -1),
  COALESCE(dm.merchant_sk, -1),
  COALESCE(dp.product_sk, -1),
  oi.order_id,
  oi.line_no,
  oi.quantity,
  oi.unit_price,
  ROUND(oi.quantity * oi.unit_price, 2),
  ROUND(oi.discount_amt, 2),
  ROUND(oi.quantity * oi.unit_price - oi.discount_amt, 2),
  ROUND((oi.quantity * oi.unit_price - oi.discount_amt) * COALESCE(dm.commission_pct, 0), 2),
  ROUND(oi.quantity * COALESCE(dp.unit_cost, 0), 2),
  ROUND(oi.quantity * oi.unit_price - oi.discount_amt - oi.quantity * COALESCE(dp.unit_cost, 0), 2),
  CASE WHEN o.status IN ('paid', 'refunded') THEN 1 ELSE 0 END
FROM order_items oi
JOIN orders o        ON o.order_id = oi.order_id
LEFT JOIN dim_date dd     ON dd.full_date = date(o.order_ts)
LEFT JOIN dim_user du     ON du.user_id = o.user_id
LEFT JOIN dim_merchant dm ON dm.merchant_id = oi.merchant_id AND dm.is_current = 1
LEFT JOIN dim_product dp  ON dp.product_id = oi.product_id AND dp.is_current = 1;

-- ---------------------------------------------------------------------------
-- fact_transaction - the money-movement fact, one row per attempt.
-- approved_amount / declined_amount are pre-split so that both are additive.
-- Decline RATE is deliberately absent: it is a ratio, and storing it would let
-- someone average an average. Numerator and denominator only.
-- ---------------------------------------------------------------------------
INSERT INTO fact_transaction (
  date_key, time_key, user_sk, payment_method_key, txn_id, order_id,
  amount, is_approved, is_declined, is_refund,
  approved_amount, declined_amount, decline_reason)
SELECT
  COALESCE(dd.date_key, -1),
  COALESCE(CAST(strftime('%H', t.txn_ts) AS INTEGER), 0),
  COALESCE(du.user_sk, -1),
  COALESCE(pm.payment_method_key, -1),
  t.txn_id,
  t.order_id,
  ROUND(t.amount, 2),
  CASE WHEN t.status = 'approved' THEN 1 ELSE 0 END,
  CASE WHEN t.status = 'declined' THEN 1 ELSE 0 END,
  CASE WHEN t.status = 'refunded' THEN 1 ELSE 0 END,
  ROUND(CASE WHEN t.status = 'approved' THEN t.amount ELSE 0 END, 2),
  ROUND(CASE WHEN t.status = 'declined' THEN t.amount ELSE 0 END, 2),
  COALESCE(t.decline_reason, 'none')
FROM transactions t
JOIN orders o ON o.order_id = t.order_id
LEFT JOIN dim_date dd            ON dd.full_date = date(t.txn_ts)
LEFT JOIN dim_user du            ON du.user_id = o.user_id
LEFT JOIN dim_payment_method pm  ON pm.payment_method = t.payment_method;

-- ---------------------------------------------------------------------------
-- fact_cart - the demand fact, one row per cart.
-- A cart can hold products from one merchant in this marketplace, but the model
-- still has to CHOOSE a merchant key: we take the merchant of the highest-value
-- line ("dominant merchant"). That choice is a modeling decision with a cost -
-- a mixed cart attributes all its abandonment to one merchant. It is documented
-- in semantic/contract.yaml so nobody reads it as truth by accident.
-- ---------------------------------------------------------------------------
INSERT INTO fact_cart (
  date_key, time_key, user_sk, merchant_sk, cart_id, order_id,
  items_count, units_count, cart_value, converted_flag, abandoned_value, minutes_to_order)
SELECT
  COALESCE(dd.date_key, -1),
  COALESCE(CAST(strftime('%H', c.created_ts) AS INTEGER), 0),
  COALESCE(du.user_sk, -1),
  COALESCE(dm.merchant_sk, -1),
  c.cart_id,
  o.order_id,
  agg.items_count,
  agg.units_count,
  ROUND(agg.cart_value, 2),
  CASE WHEN o.order_id IS NOT NULL THEN 1 ELSE 0 END,
  ROUND(CASE WHEN o.order_id IS NULL THEN agg.cart_value ELSE 0 END, 2),
  CASE WHEN o.order_id IS NULL THEN NULL
       ELSE ROUND((julianday(o.order_ts) - julianday(c.created_ts)) * 1440, 1) END
FROM carts c
JOIN (
  SELECT ci.cart_id,
         COUNT(*)                                AS items_count,
         SUM(ci.quantity)                        AS units_count,
         SUM(ci.quantity * p.list_price)         AS cart_value,
         -- dominant merchant: the one on the highest-value line in the cart
         (SELECT p2.merchant_id
            FROM cart_items ci2
            JOIN products p2 ON p2.product_id = ci2.product_id
           WHERE ci2.cart_id = ci.cart_id
           ORDER BY ci2.quantity * p2.list_price DESC, p2.merchant_id
           LIMIT 1)                              AS dominant_merchant_id
    FROM cart_items ci
    JOIN products p ON p.product_id = ci.product_id
   GROUP BY ci.cart_id
) agg ON agg.cart_id = c.cart_id
LEFT JOIN orders o        ON o.cart_id = c.cart_id
LEFT JOIN dim_date dd     ON dd.full_date = date(c.created_ts)
LEFT JOIN dim_user du     ON du.user_id = c.user_id
LEFT JOIN dim_merchant dm ON dm.merchant_id = agg.dominant_merchant_id AND dm.is_current = 1;
