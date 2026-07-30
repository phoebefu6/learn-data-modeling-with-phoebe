# Bazaar schema card

This is the entire context an AI agent gets before writing SQL against Bazaar. It is
deliberately short: a schema card is not documentation for humans, it is the prompt. Every
line here either prevents a specific wrong query or earns its tokens some other way.

Bazaar is a multi-merchant ecommerce marketplace. The database is SQLite. You may query the
five views below and nothing else - no base tables, no writes.

## Views

### v_sales_line - what was sold
One row per product line on one order. Use for revenue, units, margin, commission, sliced by
merchant, product, category, price tier, user, date, or hour.

`order_date, order_year, order_month_name, order_day_name, is_weekend, order_hour,
order_hour_label, order_daypart, merchant_id, merchant_name, merchant_category, merchant_tier,
product_id, product_name, product_category, product_price_tier, product_status, user_id,
user_country, user_city, user_acquisition_channel, user_tenure_bucket, order_id, line_no,
units, gross_revenue, discount, net_revenue, commission, margin, is_paid`

- `net_revenue` is THE revenue measure. `gross_revenue` is pre-discount and is almost never
  what anyone means.
- **Always filter `is_paid = 1` for money questions.** Unpaid lines are orders whose payment
  never settled.
- **`COUNT(*)` counts LINES, not orders.** Orders are `COUNT(DISTINCT order_id)`.
- `product_price_tier` is budget / mid / premium, defined once in the model. Do not invent a
  price threshold of your own.
- `product_status` is operational ('active' / 'out_of_stock'), not a category.

### v_payment_attempt - what was paid
One row per payment attempt. One order can have several: a decline, a retry, a refund. Use
for approvals, declines, decline reasons, settled money, payment methods, peak hours.

`attempt_date, attempt_day_name, is_weekend, attempt_hour, attempt_hour_label, attempt_daypart,
payment_method, payment_method_label, payment_method_family, user_id, user_country, order_id,
txn_id, attempt_amount, approved_amount, declined_amount, is_approved, is_declined, is_refund,
decline_reason`

- `attempt_amount` is signed: refunds are negative.
- An attempt has no product and no merchant. Product questions belong to `v_sales_line`.

### v_cart - what was wanted
One row per cart. Use for demand, abandonment, conversion.

`cart_date, cart_day_name, cart_hour, cart_daypart, dominant_merchant_id,
dominant_merchant_name, user_id, user_acquisition_channel, cart_id, order_id, distinct_products,
units, cart_value, is_converted, abandoned_value, minutes_to_order`

- `cart_value` is LIST value of the contents, not revenue.
- `abandoned_value` is already zero for converted carts - just sum it.
- `order_id` is NULL when the cart was abandoned.

### v_merchant_day - pre-aggregated, one row per merchant per day
`activity_date, merchant_id, merchant_name, merchant_category, merchant_tier, orders, units,
net_revenue, commission, margin, aov_numerator, aov_denominator`

Already filtered to settled money. Divide `aov_numerator / aov_denominator` for AOV.

### v_hour_of_day - pre-aggregated, one row per hour per weekend flag
`hour_24, hour_label, daypart, is_weekend, attempts, approvals, declines, approved_amount`

`SUM(attempts)` for volume. Counting rows here counts hour-buckets, not transactions.

## Hard rules

1. **Never join `v_sales_line` to `v_payment_attempt`.** They are different grains: one order
   with 3 lines and 2 payment attempts produces 6 rows and revenue inflated 2x. If a question
   needs both, aggregate each separately (subqueries) and compare.
2. **Never store or average a ratio.** Compute rates as `SUM(numerator) / SUM(denominator)` at
   the grain of the question. `AVG(per_row_percentage)` is always wrong.
3. **Always return a rate's denominator beside it.** A 20% decline rate on 10 attempts is
   noise; the reader cannot tell without the count.
4. **Put a volume floor on any "which X is worst/best by rate" question** (e.g.
   `HAVING COUNT(*) >= 30`), or the answer is whichever X has the fewest observations.
5. **Look up metric definitions in `v_metric_definitions`** before inventing one. It holds the
   name, the SQL expression, the source view, the grain, and the caveat for every metric.
6. **Show the SQL with the answer.** A number with no query cannot be checked by anyone.

## Data range

2026-04-01 to 2026-06-29. Currency SGD throughout. 12 merchants (M01-M12), 60 products,
60 users.
