-- ============================================================================
-- 20_marts.sql - the four marts the business actually reads (session b8)
--
-- A mart is not "a smaller copy of the star". It is the star pre-aggregated to
-- the grain a specific set of questions is asked at, with the metric definitions
-- baked in so that two people asking the same question get the same number.
--
-- Each mart below states its grain and the questions it serves. Notice that no
-- mart stores a ratio: every rate is shipped as numerator + denominator, and the
-- division happens at read time. That is the single discipline that stops
-- "average of averages" bugs, and it is what makes these marts safe to hand to
-- an AI agent in session b9.
--
-- Run after 12_oltp_to_star.sql.
-- ============================================================================

DROP TABLE IF EXISTS mart_merchant_daily;
DROP TABLE IF EXISTS mart_hourly_transactions;
DROP TABLE IF EXISTS mart_funnel_daily;
DROP TABLE IF EXISTS mart_payment_health_daily;

-- ---------------------------------------------------------------------------
-- mart_merchant_daily
-- GRAIN: one row per merchant per day.
-- Serves: "which merchant's performance dropped", "revenue by merchant/tier",
--         "where did GMV go", merchant-level margin and commission.
-- ---------------------------------------------------------------------------
CREATE TABLE mart_merchant_daily AS
SELECT
  d.full_date                                   AS activity_date,
  d.date_key                                    AS date_key,
  m.merchant_id                                 AS merchant_id,
  m.merchant_name                               AS merchant_name,
  m.category                                    AS merchant_category,
  m.tier                                        AS merchant_tier,
  COUNT(DISTINCT f.order_id)                    AS orders,
  SUM(f.quantity)                               AS units,
  ROUND(SUM(f.gross_amount), 2)                 AS gross_revenue,
  ROUND(SUM(f.discount_amount), 2)              AS discounts,
  ROUND(SUM(f.net_amount), 2)                   AS net_revenue,
  ROUND(SUM(f.commission_amount), 2)            AS commission,
  ROUND(SUM(f.margin_amount), 2)                AS margin,
  -- numerator / denominator for AOV, never the ratio itself
  ROUND(SUM(f.net_amount), 2)                   AS aov_numerator,
  COUNT(DISTINCT f.order_id)                    AS aov_denominator
FROM fact_order_item f
JOIN dim_date d     ON d.date_key = f.date_key
JOIN dim_merchant m ON m.merchant_sk = f.merchant_sk
WHERE f.is_paid = 1                             -- money that actually settled
GROUP BY d.full_date, d.date_key, m.merchant_id, m.merchant_name, m.category, m.tier;

-- ---------------------------------------------------------------------------
-- mart_hourly_transactions
-- GRAIN: one row per date per hour.
-- Serves: "what are our peak transaction hours", staffing and on-call windows,
--         "when should the deploy freeze be".
-- Built from fact_transaction, not fact_order_item, because the question is
-- about when money MOVES, and an order placed at 23:58 can settle at 00:03.
-- ---------------------------------------------------------------------------
CREATE TABLE mart_hourly_transactions AS
SELECT
  d.full_date                                             AS activity_date,
  d.day_name                                              AS day_name,
  d.is_weekend                                            AS is_weekend,
  t.time_key                                              AS hour_24,
  t.hour_label                                            AS hour_label,
  t.daypart                                               AS daypart,
  COUNT(*)                                                AS attempts,
  SUM(f.is_approved)                                      AS approvals,
  SUM(f.is_declined)                                      AS declines,
  ROUND(SUM(f.approved_amount), 2)                        AS approved_amount,
  ROUND(SUM(f.declined_amount), 2)                        AS declined_amount,
  COUNT(DISTINCT f.order_id)                              AS orders_touched
FROM fact_transaction f
JOIN dim_date d          ON d.date_key = f.date_key
JOIN dim_time_of_day t   ON t.time_key = f.time_key
GROUP BY d.full_date, d.day_name, d.is_weekend, t.time_key, t.hour_label, t.daypart;

-- ---------------------------------------------------------------------------
-- mart_funnel_daily
-- GRAIN: one row per day.
-- Serves: "why did sales drop" - the decomposition mart. Sales = carts x
--         conversion x AOV, so a drop is always one of those three moving, and
--         this mart holds all three at one grain so the arithmetic is checkable.
-- ---------------------------------------------------------------------------
CREATE TABLE mart_funnel_daily AS
WITH carts AS (
  SELECT d.full_date            AS activity_date,
         COUNT(*)               AS carts_created,
         SUM(c.converted_flag)  AS carts_converted,
         ROUND(SUM(c.cart_value), 2)      AS cart_value,
         ROUND(SUM(c.abandoned_value), 2) AS abandoned_value
    FROM fact_cart c
    JOIN dim_date d ON d.date_key = c.date_key
   GROUP BY d.full_date
),
sales AS (
  SELECT d.full_date                        AS activity_date,
         COUNT(DISTINCT f.order_id)         AS paid_orders,
         ROUND(SUM(f.net_amount), 2)        AS net_revenue,
         SUM(f.quantity)                    AS units
    FROM fact_order_item f
    JOIN dim_date d ON d.date_key = f.date_key
   WHERE f.is_paid = 1
   GROUP BY d.full_date
),
pay AS (
  SELECT d.full_date               AS activity_date,
         COUNT(*)                  AS payment_attempts,
         SUM(f.is_declined)        AS declines,
         ROUND(SUM(f.declined_amount), 2) AS declined_amount
    FROM fact_transaction f
    JOIN dim_date d ON d.date_key = f.date_key
   GROUP BY d.full_date
)
SELECT
  c.activity_date,
  c.carts_created,
  c.carts_converted,
  c.cart_value,
  c.abandoned_value,
  COALESCE(s.paid_orders, 0)   AS paid_orders,
  COALESCE(s.net_revenue, 0)   AS net_revenue,
  COALESCE(s.units, 0)         AS units,
  COALESCE(p.payment_attempts, 0) AS payment_attempts,
  COALESCE(p.declines, 0)      AS declines,
  COALESCE(p.declined_amount, 0) AS declined_amount
FROM carts c
LEFT JOIN sales s ON s.activity_date = c.activity_date
LEFT JOIN pay   p ON p.activity_date = c.activity_date;

-- ---------------------------------------------------------------------------
-- mart_payment_health_daily
-- GRAIN: one row per day per payment method.
-- Serves: "is the drop a demand problem or a payments problem", decline-reason
--         triage, "which wallet is failing".
-- ---------------------------------------------------------------------------
CREATE TABLE mart_payment_health_daily AS
SELECT
  d.full_date                        AS activity_date,
  pm.payment_method                  AS payment_method,
  pm.method_label                    AS method_label,
  pm.method_family                   AS method_family,
  COUNT(*)                           AS attempts,
  SUM(f.is_approved)                 AS approvals,
  SUM(f.is_declined)                 AS declines,
  SUM(f.is_refund)                   AS refunds,
  ROUND(SUM(f.approved_amount), 2)   AS approved_amount,
  ROUND(SUM(f.declined_amount), 2)   AS declined_amount,
  -- the most common decline reason of the day, for triage.
  -- COALESCE to 'none' rather than NULL: a method-day with zero declines is a
  -- real, meaningful row, and a NULL here would drop it from any GROUP BY.
  COALESCE((SELECT f2.decline_reason
     FROM fact_transaction f2
    WHERE f2.date_key = d.date_key
      AND f2.payment_method_key = pm.payment_method_key
      AND f2.is_declined = 1
    GROUP BY f2.decline_reason
    ORDER BY COUNT(*) DESC, f2.decline_reason
    LIMIT 1), 'none')                AS top_decline_reason
FROM fact_transaction f
JOIN dim_date d            ON d.date_key = f.date_key
JOIN dim_payment_method pm ON pm.payment_method_key = f.payment_method_key
GROUP BY d.full_date, d.date_key, pm.payment_method, pm.method_label,
         pm.method_family, pm.payment_method_key;

-- ============================================================================
-- Why four marts and not one: each has a different grain. Merging them would
-- force a grain that fits none of them and re-introduce exactly the fan-out
-- double-count that fact separation exists to prevent. When two marts must be
-- read together, join them on their shared conformed keys (activity_date,
-- merchant_id) - which works precisely because both were built from the same
-- dimensions.
-- ============================================================================
