-- ============================================================================
-- 30_business_questions.sql - the four questions the model was built to answer
--                             (session b8)
--
-- These are the questions a marketplace leadership team asks on a Monday. Each
-- one is answered here in SQL that reads like the question, because the model
-- did the hard work first. Try writing any of them against the raw OLTP tables
-- in 01/02 and you will feel the difference - that feeling is the entire
-- argument for dimensional modeling.
--
-- Every query is runnable as-is against the star + marts. Numbers below the
-- queries are the answers this dataset (seed 42) actually produces, so you can
-- confirm your run matches.
--
-- Run after 20_marts.sql.
-- ============================================================================


-- ============================================================================
-- Q1 · WHICH MERCHANT'S PERFORMANCE DROPPED?
--
-- The comparison is last 14 days vs the 14 before it. Two things matter and both
-- are shown: the ABSOLUTE dollars lost (what the business feels) and the PERCENT
-- change (how bad it is for that merchant). Ranking by percent alone promotes
-- tiny merchants; ranking by dollars alone hides a small merchant in freefall.
--
-- The volume-vs-price split at the end is the diagnostic: did they sell fewer
-- orders, or the same orders at a lower value? Those have different fixes.
-- ============================================================================
WITH windows AS (
  SELECT
    merchant_id, merchant_name, merchant_tier,
    SUM(CASE WHEN activity_date >= '2026-06-16' THEN net_revenue ELSE 0 END) AS rev_recent,
    SUM(CASE WHEN activity_date >= '2026-06-02'
              AND activity_date <  '2026-06-16' THEN net_revenue ELSE 0 END) AS rev_prior,
    SUM(CASE WHEN activity_date >= '2026-06-16' THEN orders ELSE 0 END)      AS orders_recent,
    SUM(CASE WHEN activity_date >= '2026-06-02'
              AND activity_date <  '2026-06-16' THEN orders ELSE 0 END)      AS orders_prior
  FROM mart_merchant_daily
  GROUP BY merchant_id, merchant_name, merchant_tier
)
SELECT
  merchant_id,
  merchant_name,
  merchant_tier,
  ROUND(rev_prior, 0)                  AS revenue_prior_14d,
  ROUND(rev_recent, 0)                 AS revenue_recent_14d,
  ROUND(rev_recent - rev_prior, 0)     AS dollars_change,
  CASE WHEN rev_prior = 0 THEN NULL
       ELSE ROUND(100.0 * (rev_recent - rev_prior) / rev_prior, 1) END AS pct_change,
  orders_prior                         AS orders_prior_14d,
  orders_recent                        AS orders_recent_14d,
  -- the split: is it fewer orders, or smaller orders?
  CASE WHEN orders_prior = 0 THEN NULL
       ELSE ROUND(100.0 * (orders_recent - orders_prior) / orders_prior, 1) END AS pct_change_orders,
  CASE
    WHEN rev_recent >= rev_prior THEN 'no drop'
    WHEN orders_prior > 0 AND orders_recent * 1.0 / orders_prior < 0.85 THEN 'volume driven'
    ELSE 'order-value driven'
  END                                  AS drop_shape
FROM windows
ORDER BY dollars_change ASC
LIMIT 5;

-- Answer in this dataset:
--   M07 Nimbus Audio   3,063 -> 455    -2,609   -85.2%   volume driven
--   M02 Verdant Skin   2,655 -> 1,166  -1,489   -56.1%   volume driven
--   M04 Pace Athletics 3,418 -> 2,115  -1,303   -38.1%   volume driven
--   M12 Fable Toys     1,555 -> 404    -1,151   -74.0%   volume driven
--   M11 Orchid Grocer  3,110 -> 2,104  -1,006   -32.3%   volume driven
--
-- Read that carefully, because it is the trap: EVERY merchant is down. If you
-- stop at "M07 dropped 85%" you will go and manage M07 and miss that the whole
-- marketplace fell. A merchant ranking alone cannot tell you whether the cause
-- is one merchant or the platform - it has no denominator. That is Q2's job.
-- M07 is still special (it falls twice as hard as the next one), but it is one
-- of two causes, not the cause.


-- ============================================================================
-- Q2 · WHY DID SALES DROP? (the decomposition)
--
-- Never answer this with one number. Revenue = carts x conversion x AOV, and a
-- drop is one of those three. This query lays all three side by side for the two
-- windows, so the cause is visible instead of argued about.
--
-- Ratios are computed here at read time from the numerator/denominator columns
-- the mart stores - which is why the two windows are comparable at all.
-- ============================================================================
WITH w AS (
  SELECT
    CASE WHEN activity_date >= '2026-06-16' THEN 'recent_14d' ELSE 'prior_14d' END AS window_label,
    SUM(carts_created)    AS carts,
    SUM(carts_converted)  AS conversions,
    SUM(paid_orders)      AS paid_orders,
    SUM(net_revenue)      AS net_revenue,
    SUM(payment_attempts) AS attempts,
    SUM(declines)         AS declines,
    SUM(abandoned_value)  AS abandoned_value
  FROM mart_funnel_daily
  WHERE activity_date >= '2026-06-02'
  GROUP BY window_label
)
SELECT
  window_label,
  carts,
  ROUND(100.0 * conversions / carts, 1)          AS conversion_rate_pct,
  paid_orders,
  ROUND(net_revenue, 0)                          AS net_revenue,
  ROUND(net_revenue / NULLIF(paid_orders, 0), 2) AS aov,
  ROUND(100.0 * declines / NULLIF(attempts, 0), 1) AS decline_rate_pct,
  ROUND(abandoned_value, 0)                      AS abandoned_value
FROM w
ORDER BY window_label DESC;

-- Answer in this dataset:
--   window       carts  conv%   orders  revenue   AOV     decline%  abandoned
--   recent_14d   312    44.9    135     15,963    118.25  4.1       19,010
--   prior_14d    398    47.2    178     22,906    128.68  10.3      23,983
--
-- Now the drop decomposes without argument. Revenue is down 30%. Carts are down
-- 22%, conversion is flat (-2.3pp), AOV is down 8%. So roughly three quarters of
-- the loss is FEWER CARTS - top-of-funnel demand - and the rest is smaller
-- orders. Conversion did not break, and the decline rate actually IMPROVED
-- (10.3% -> 4.1%), because the prior window contains the 2026-06-10 checkout
-- incident that Q3 is about.
--
-- That is the whole reason to decompose: "sales dropped 30%" sends everyone to
-- the checkout team. The model says go to marketing (carts) and to M07.

-- ---- Q2b · test the two remaining hypotheses ----
-- One query per hypothesis. Each one either survives or dies - that is the only
-- honest way to use a model diagnostically.
SELECT
  'declines by merchant, recent 14d' AS check_name,
  m.merchant_id,
  m.merchant_name,
  COUNT(*)                                             AS attempts,
  SUM(f.is_declined)                                   AS declines,
  ROUND(100.0 * SUM(f.is_declined) / COUNT(*), 1)      AS decline_rate_pct
FROM fact_transaction f
JOIN dim_date d ON d.date_key = f.date_key
JOIN fact_order_item foi ON foi.order_id = f.order_id AND foi.line_no = 1  -- one line per order, on purpose
JOIN dim_merchant m ON m.merchant_sk = foi.merchant_sk
WHERE d.full_date >= '2026-06-16'
GROUP BY m.merchant_id, m.merchant_name
ORDER BY decline_rate_pct DESC
LIMIT 5;

-- NOTE the join above: fact_transaction is joined to fact_order_item ONLY at
-- line_no = 1, so one order contributes one row. Join the two facts without
-- that filter and a three-line order multiplies its payments by three - the
-- exact double-count session b9 makes an AI agent commit and then catches.

SELECT
  'out-of-stock products' AS check_name,
  p.merchant_id,
  p.product_name,
  p.status,
  ROUND(SUM(CASE WHEN d.full_date <  '2026-06-15' THEN f.net_amount ELSE 0 END), 0) AS revenue_before,
  ROUND(SUM(CASE WHEN d.full_date >= '2026-06-15' THEN f.net_amount ELSE 0 END), 0) AS revenue_after
FROM fact_order_item f
JOIN dim_product p ON p.product_sk = f.product_sk
JOIN dim_date d    ON d.date_key = f.date_key
WHERE p.status = 'out_of_stock'
GROUP BY p.merchant_id, p.product_name, p.status
ORDER BY revenue_before DESC;

-- Answers in this dataset - one hypothesis dies, one survives:
--
--   DIED: "M07 has a payments problem." The decline ranking puts M10 first at
--   18.2% (2 declines out of 11 attempts) and M07 second at 10.0% (1 of 10).
--   Those are 10-attempt samples: at that volume one decline moves the rate by
--   9 points, so the ranking is noise wearing a percentage sign. A model tells
--   you the number; it cannot tell you the number is meaningless. Always print
--   the denominator next to a rate - this query does, which is why the
--   hypothesis is refutable at all.
--
--   SURVIVED: M07's hero product, Studio Headphones, earned 3,646 before
--   2026-06-15 and exactly 0 after. It went out of stock. That is a supply
--   failure, not a demand or payments failure, and it explains the bulk of one
--   merchant's collapse on its own.
--
-- Final diagnosis: two independent causes. A platform-wide demand drop (carts
-- -22%, from the paid-search pullback on 2026-06-18) plus M07 losing its hero
-- SKU to stockout. Neither is a checkout problem, which is where the room would
-- have started guessing.


-- ============================================================================
-- Q3 · WHY THE DIP ON A SPECIFIC DAY?
--
-- Day-level driver attribution. The shape of the answer matters: orders were
-- placed, so demand was fine - the money did not settle. That distinction is
-- only possible because carts, orders and payment attempts are three separate
-- facts. Collapse them into one table and this question becomes unanswerable.
-- ============================================================================
SELECT
  activity_date,
  carts_created,
  carts_converted,
  paid_orders,
  ROUND(net_revenue, 0)                              AS net_revenue,
  payment_attempts,
  declines,
  ROUND(100.0 * declines / NULLIF(payment_attempts, 0), 1) AS decline_rate_pct,
  ROUND(declined_amount, 0)                          AS money_that_failed
FROM mart_funnel_daily
WHERE activity_date BETWEEN '2026-06-07' AND '2026-06-13'
ORDER BY activity_date;

-- Answer in this dataset:
--   date         carts  converted  paid_orders  revenue  attempts  declines  rate%
--   2026-06-09   29     13         12           1,338    15        2         13.3
--   2026-06-10   24     13         8            484      17        9         52.9
--   2026-06-11   31     14         14           1,967    16        1         6.3
--
-- Carts normal, conversions normal, orders placed - and revenue collapses to
-- 484 from a ~1,900 baseline because 9 of 17 payment attempts failed. Demand was
-- fine; checkout broke. The reason code names it:
SELECT top_decline_reason, SUM(declines) AS declines, ROUND(SUM(declined_amount), 0) AS value
FROM mart_payment_health_daily
WHERE activity_date = '2026-06-10'
  AND declines > 0
GROUP BY top_decline_reason
ORDER BY declines DESC;
-- gateway_timeout, 9 declines, 740 of failed money - an infrastructure incident,
-- not a market. Note what made this answerable: carts, orders and payment
-- attempts are three separate facts at three grains. Flatten them into one
-- table and "they wanted to buy but could not pay" has nowhere to live.


-- ============================================================================
-- Q4 · WHAT ARE OUR PEAK TRANSACTION HOURS?
--
-- The question every ops, on-call and staffing conversation needs. Answered
-- across all 90 days at once, which is only cheap because hour is a dimension
-- rather than something to be parsed out of a timestamp 1,120 times.
-- ============================================================================
SELECT
  hour_label,
  daypart,
  SUM(attempts)                                      AS attempts,
  SUM(approvals)                                     AS approvals,
  ROUND(SUM(approved_amount), 0)                     AS approved_amount,
  ROUND(100.0 * SUM(declines) / SUM(attempts), 1)    AS decline_rate_pct,
  ROUND(100.0 * SUM(attempts) / (SELECT SUM(attempts) FROM mart_hourly_transactions), 1)
                                                     AS pct_of_all_attempts
FROM mart_hourly_transactions
GROUP BY hour_label, daypart
ORDER BY attempts DESC
LIMIT 6;

-- Answer in this dataset (attempts, all 90 days):
--   21:00-21:59  96   evening   9.1% of all attempts
--   19:00-19:59  94   evening   8.9%
--   13:00-13:59  89   lunch     8.4%
--   20:00-20:59  89   evening   8.4%
--   22:00-22:59  77   evening   7.3%
--   12:00-12:59  75   lunch     7.1%
--
-- So: a broad evening peak 19:00-22:59 carrying about a third of all attempts,
-- and a secondary lunch peak 12:00-13:59. Overnight 01:00-05:00 is nearly dead.
-- Deploy windows belong at 03:00-05:00; on-call cover belongs 19:00-23:00.

-- Weekday vs weekend, because "peak hour" differs between them and one blended
-- answer would mislead a staffing decision:
SELECT
  CASE WHEN is_weekend = 1 THEN 'weekend' ELSE 'weekday' END AS day_type,
  hour_label,
  SUM(attempts) AS attempts
FROM mart_hourly_transactions
GROUP BY day_type, hour_label
ORDER BY day_type, attempts DESC;

-- And they do differ: weekday peaks at 20:00 (64 attempts), weekend peaks at
-- 21:00 (41) with a much flatter afternoon. A single blended "peak hour" would
-- have staffed the wrong hour on one of the two.

-- ============================================================================
-- The point of this file: four business questions, four short queries, zero
-- arguments about definitions. That is what a model is FOR. The same four
-- questions against the raw OLTP source need window functions, date parsing,
-- fan-out guards and a shared understanding of "revenue" that nobody wrote down.
-- ============================================================================
