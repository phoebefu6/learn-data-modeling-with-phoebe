-- ============================================================================
-- 10_dim_ddl.sql - Bazaar's dimensions (session b6)
--
-- Six dimensions. Every one answers "by what?" - by merchant, by product, by
-- user, by date, by hour, by payment method. Facts answer "how much?"; dims
-- answer "sliced how?". If a business question contains the word "by", the word
-- after it is a dimension.
--
-- Rules applied in every table below:
--   1. SURROGATE KEY on every dimension (*_sk), an integer that means nothing.
--      The natural key (merchant_id, product_id, user_id) rides along as a
--      business key you can still join and read. The surrogate exists so that
--      history can change without breaking old facts - see rule 3.
--   2. FLAT AND WIDE, not normalized. dim_product carries its merchant's name
--      and category as columns even though merchants has them too. That
--      duplication is deliberate: it removes a join from every analyst query
--      and every generated query an AI agent writes. In OLTP, duplication is a
--      bug. In a dimension, it is the product. (Snowflaking - normalizing dims
--      back out - is the pattern we are choosing against, and b6 says when it
--      is defensible.)
--   3. SCD TYPE 2 on the two dims whose attributes change and whose history
--      matters: dim_merchant (tier, commission_pct) and dim_product
--      (list_price, status). Each version is a row with valid_from / valid_to /
--      is_current. A fact joins to the version that was true when it happened,
--      so "revenue by merchant tier" reports the tier at time of sale, not the
--      tier today. dim_user is Type 1 (overwrite) because nobody has ever asked
--      for the history of a shopper's city.
--      NOTE: this file is the DESIGN and the initial load. The mechanics of
--      applying a type-2 change on every run belong to the sibling course
--      learn-data-warehouse (builder session 5) - it is a loading problem, not
--      a modeling problem.
--   4. NO NULLS IN DIMENSION ATTRIBUTES. Unknown becomes the literal string
--      'unknown' and unknown keys point at the -1 row. A NULL in a dimension
--      silently drops rows from every inner join, which is how a dashboard
--      loses 4% of revenue and nobody notices for a quarter.
-- ============================================================================

DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_time_of_day;
DROP TABLE IF EXISTS dim_user;
DROP TABLE IF EXISTS dim_merchant;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_payment_method;

-- ---------------------------------------------------------------- dim_date
-- The one dimension you never source from an application. It is generated,
-- covers a range wider than your data, and holds every calendar attribute
-- anyone will ever group by. date_key is a readable integer (20260610), which
-- makes fact tables scannable by eye and partitionable by prefix.
CREATE TABLE dim_date (
  date_key     INTEGER PRIMARY KEY,   -- 20260610
  full_date    TEXT NOT NULL UNIQUE,  -- '2026-06-10'
  year         INTEGER NOT NULL,
  quarter      INTEGER NOT NULL,
  month        INTEGER NOT NULL,
  month_name   TEXT NOT NULL,
  day_of_month INTEGER NOT NULL,
  day_of_week  INTEGER NOT NULL,      -- 0 = Sunday, SQLite's %w
  day_name     TEXT NOT NULL,
  week_of_year INTEGER NOT NULL,
  is_weekend   INTEGER NOT NULL CHECK (is_weekend IN (0, 1))
);

-- ---------------------------------------------------------------- dim_time_of_day
-- Hour-grain time dimension, separate from dim_date on purpose. Putting hours
-- in dim_date would multiply it by 24 for no benefit; keeping them apart lets
-- "peak transaction hour" (session b8) group across all 90 days at once.
-- daypart is the label a business person actually says out loud.
CREATE TABLE dim_time_of_day (
  time_key    INTEGER PRIMARY KEY CHECK (time_key BETWEEN 0 AND 23),
  hour_24     INTEGER NOT NULL,
  hour_label  TEXT NOT NULL,          -- '09:00-09:59'
  daypart     TEXT NOT NULL,          -- overnight / morning / lunch / afternoon / evening / late
  is_business_hour INTEGER NOT NULL CHECK (is_business_hour IN (0, 1))
);

-- ---------------------------------------------------------------- dim_user
-- SCD Type 1: attributes are overwritten in place. tenure_bucket is a
-- pre-computed band so nobody writes a different CASE expression in every
-- dashboard and gets a different answer.
CREATE TABLE dim_user (
  user_sk             INTEGER PRIMARY KEY,
  user_id             INTEGER NOT NULL UNIQUE,   -- business key
  country             TEXT NOT NULL DEFAULT 'unknown',
  city                TEXT NOT NULL DEFAULT 'unknown',
  acquisition_channel TEXT NOT NULL DEFAULT 'unknown',
  signup_date         TEXT,
  tenure_bucket       TEXT NOT NULL DEFAULT 'unknown',  -- new / 3-12m / 1y+
  is_guest            INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------- dim_merchant (SCD2)
-- One row per merchant PER VERSION. The current row has valid_to = '9999-12-31'
-- and is_current = 1. Facts store merchant_sk, so a sale in April keeps
-- pointing at April's tier even after the merchant is promoted in June.
CREATE TABLE dim_merchant (
  merchant_sk    INTEGER PRIMARY KEY,
  merchant_id    TEXT NOT NULL,             -- business key, NOT unique here (versions)
  merchant_name  TEXT NOT NULL,
  category       TEXT NOT NULL DEFAULT 'unknown',
  country        TEXT NOT NULL DEFAULT 'unknown',
  tier           TEXT NOT NULL DEFAULT 'unknown',
  commission_pct REAL NOT NULL DEFAULT 0,
  joined_date    TEXT,
  valid_from     TEXT NOT NULL,
  valid_to       TEXT NOT NULL DEFAULT '9999-12-31',
  is_current     INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1))
);
CREATE INDEX idx_dim_merchant_bk ON dim_merchant(merchant_id, is_current);

-- ---------------------------------------------------------------- dim_product (SCD2)
-- Carries the merchant's name and category (flattened, rule 2) plus a
-- price_tier band. price_tier is a MODELED attribute, not a source column - the
-- source has a price, the business thinks in budget/mid/premium, and the
-- dimension is where that translation lives once instead of in ten queries.
CREATE TABLE dim_product (
  product_sk     INTEGER PRIMARY KEY,
  product_id     INTEGER NOT NULL,          -- business key, versions allowed
  sku            TEXT NOT NULL,
  product_name   TEXT NOT NULL,
  category       TEXT NOT NULL DEFAULT 'unknown',
  merchant_id    TEXT NOT NULL,
  merchant_name  TEXT NOT NULL DEFAULT 'unknown',
  list_price     REAL NOT NULL DEFAULT 0,
  unit_cost      REAL NOT NULL DEFAULT 0,
  price_tier     TEXT NOT NULL DEFAULT 'unknown',   -- budget / mid / premium
  status         TEXT NOT NULL DEFAULT 'unknown',
  launched_date  TEXT,
  valid_from     TEXT NOT NULL,
  valid_to       TEXT NOT NULL DEFAULT '9999-12-31',
  is_current     INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1))
);
CREATE INDEX idx_dim_product_bk ON dim_product(product_id, is_current);

-- ---------------------------------------------------------------- dim_payment_method
-- A small dimension that exists because grouping by a raw source string
-- ('card_visa') is not the grouping anyone wants. method_family lets you say
-- "cards vs wallets vs bank" in one GROUP BY instead of a CASE statement that
-- differs per analyst.
CREATE TABLE dim_payment_method (
  payment_method_key INTEGER PRIMARY KEY,
  payment_method     TEXT NOT NULL UNIQUE,
  method_label       TEXT NOT NULL,
  method_family      TEXT NOT NULL,        -- card / wallet / bank
  is_card            INTEGER NOT NULL CHECK (is_card IN (0, 1))
);
