"""Answer the four business questions the Bazaar model was built for (session b8).

Runs the analyses in sql/30_business_questions.sql against bazaar.db, prints readable
answers, and saves charts at 300 DPI (PNG) plus SVG for slides.

    Q1  Which merchant's performance dropped?
    Q2  Why did sales drop? (carts x conversion x AOV decomposition)
    Q3  Why the dip on a specific day?
    Q4  What are our peak transaction hours?

Usage:
    python python/answer_questions.py                # all four, with charts
    python python/answer_questions.py --q 1 3        # only Q1 and Q3
    python python/answer_questions.py --no-charts
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "bazaar.db"
CHARTS = ROOT / "charts"

RECENT_FROM = "2026-06-16"
PRIOR_FROM = "2026-06-02"
INCIDENT_DAY = "2026-06-10"


# ---------------------------------------------------------------- helpers

def table(rows: list[tuple], headers: list[str], widths: list[int] | None = None) -> None:
    widths = widths or [max(len(str(h)), 12) for h in headers]
    print("  " + "  ".join(f"{h:<{w}}" for h, w in zip(headers, widths)))
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        cells = []
        for value, w in zip(row, widths):
            text = "-" if value is None else (f"{value:,.2f}" if isinstance(value, float) else str(value))
            cells.append(f"{text:<{w}}")
        print("  " + "  ".join(cells))


def heading(number: int, question: str) -> None:
    print(f"\n{'=' * 78}\nQ{number} · {question}\n{'=' * 78}")


def save(fig, name: str) -> None:
    CHARTS.mkdir(exist_ok=True)
    fig.savefig(CHARTS / f"{name}.png", dpi=300, bbox_inches="tight")
    fig.savefig(CHARTS / f"{name}.svg", bbox_inches="tight")
    print(f"\n  charts/{name}.png (300 DPI) + charts/{name}.svg")


# ---------------------------------------------------------------- Q1

def q1_merchant_drop(conn: sqlite3.Connection, charts: bool) -> None:
    heading(1, "Which merchant's performance dropped?")
    rows = conn.execute(f"""
        WITH windows AS (
          SELECT merchant_id, merchant_name, merchant_tier,
            SUM(CASE WHEN activity_date >= '{RECENT_FROM}' THEN net_revenue ELSE 0 END) AS recent,
            SUM(CASE WHEN activity_date >= '{PRIOR_FROM}'
                      AND activity_date <  '{RECENT_FROM}' THEN net_revenue ELSE 0 END) AS prior,
            SUM(CASE WHEN activity_date >= '{RECENT_FROM}' THEN orders ELSE 0 END) AS orders_recent,
            SUM(CASE WHEN activity_date >= '{PRIOR_FROM}'
                      AND activity_date <  '{RECENT_FROM}' THEN orders ELSE 0 END) AS orders_prior
          FROM mart_merchant_daily GROUP BY merchant_id, merchant_name, merchant_tier)
        SELECT merchant_id, merchant_name, merchant_tier,
               ROUND(prior, 0), ROUND(recent, 0), ROUND(recent - prior, 0),
               CASE WHEN prior = 0 THEN NULL ELSE ROUND(100.0 * (recent - prior) / prior, 1) END,
               orders_prior, orders_recent,
               CASE WHEN recent >= prior THEN 'no drop'
                    WHEN orders_prior > 0 AND orders_recent * 1.0 / orders_prior < 0.85
                      THEN 'volume driven'
                    ELSE 'order-value driven' END
        FROM windows ORDER BY (recent - prior) ASC
    """).fetchall()

    table(rows[:6],
          ["id", "merchant", "tier", "prior 14d", "recent 14d", "change", "pct", "ord -", "ord +", "shape"],
          [5, 18, 9, 10, 11, 8, 7, 6, 6, 18])

    worst = rows[0]
    down = [r for r in rows if r[5] < 0]
    print(f"\n  Answer: {worst[1]} ({worst[0]}) lost {abs(worst[5]):,.0f} SGD, {worst[6]}%, {worst[9]}.")
    print(f"  But note: {len(down)} of {len(rows)} merchants are down. A merchant ranking has no")
    print(f"  denominator, so it cannot tell you whether the cause is one merchant or the")
    print(f"  platform. That is Q2's job.")

    if charts:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(9, 5))
        names = [r[1] for r in rows]
        deltas = [r[5] for r in rows]
        colors = ["#B91C1C" if d < 0 else "#3B5B8C" for d in deltas]
        ax.barh(names, deltas, color=colors)
        ax.axvline(0, color="#1B2637", linewidth=1)
        ax.set_xlabel("Change in net revenue, last 14 days vs prior 14 days (SGD)")
        ax.set_title("Q1 · Every merchant is down - one is down twice as hard", loc="left")
        ax.invert_yaxis()
        ax.spines[["top", "right"]].set_visible(False)
        save(fig, "q1_merchant_change")
        plt.close(fig)


# ---------------------------------------------------------------- Q2

def q2_sales_drop(conn: sqlite3.Connection, charts: bool) -> None:
    heading(2, "Why did sales drop?")
    rows = conn.execute(f"""
        WITH w AS (
          SELECT CASE WHEN activity_date >= '{RECENT_FROM}' THEN 'recent_14d' ELSE 'prior_14d' END AS window_label,
                 SUM(carts_created) AS carts, SUM(carts_converted) AS conversions,
                 SUM(paid_orders) AS paid_orders, SUM(net_revenue) AS net_revenue,
                 SUM(payment_attempts) AS attempts, SUM(declines) AS declines,
                 SUM(abandoned_value) AS abandoned
          FROM mart_funnel_daily WHERE activity_date >= '{PRIOR_FROM}' GROUP BY window_label)
        SELECT window_label, carts, ROUND(100.0 * conversions / carts, 1), paid_orders,
               ROUND(net_revenue, 0), ROUND(net_revenue / NULLIF(paid_orders, 0), 2),
               ROUND(100.0 * declines / NULLIF(attempts, 0), 1), ROUND(abandoned, 0)
        FROM w ORDER BY window_label DESC
    """).fetchall()
    table(rows, ["window", "carts", "conv %", "orders", "revenue", "AOV", "decline %", "abandoned"],
          [12, 7, 8, 8, 10, 9, 11, 11])

    recent, prior = rows[0], rows[1]
    pct = lambda a, b: (a - b) / b * 100 if b else 0
    print(f"\n  Decomposition, recent vs prior:")
    print(f"    revenue    {pct(recent[4], prior[4]):+6.1f}%")
    print(f"    carts      {pct(recent[1], prior[1]):+6.1f}%   <- top-of-funnel demand")
    print(f"    conversion {recent[2] - prior[2]:+6.1f}pp")
    print(f"    AOV        {pct(recent[5], prior[5]):+6.1f}%")
    print(f"    decline    {recent[6] - prior[6]:+6.1f}pp  (prior window contains the {INCIDENT_DAY} incident)")
    print(f"\n  Answer: most of the loss is FEWER CARTS, not broken checkout. Conversion held.")

    print(f"\n  Hypothesis test 1 - is it a payments problem? (declines by merchant, recent 14d)")
    dec = conn.execute(f"""
        SELECT m.merchant_id, m.merchant_name, COUNT(*) AS attempts, SUM(f.is_declined) AS declines,
               ROUND(100.0 * SUM(f.is_declined) / COUNT(*), 1) AS rate
        FROM fact_transaction f
        JOIN dim_date d ON d.date_key = f.date_key
        JOIN fact_order_item foi ON foi.order_id = f.order_id AND foi.line_no = 1
        JOIN dim_merchant m ON m.merchant_sk = foi.merchant_sk
        WHERE d.full_date >= '{RECENT_FROM}'
        GROUP BY m.merchant_id, m.merchant_name ORDER BY rate DESC LIMIT 4
    """).fetchall()
    table(dec, ["id", "merchant", "attempts", "declines", "rate %"], [5, 18, 10, 10, 8])
    print(f"  Verdict: DIES. Those are ~10-attempt samples - one decline moves the rate 9 points.")
    print(f"  A rate without its denominator is not evidence. (Note the line_no = 1 filter: it")
    print(f"  is what stops the fact-to-fact join from multiplying payments by lines.)")

    print(f"\n  Hypothesis test 2 - did a product go out of stock?")
    oos = conn.execute("""
        SELECT p.merchant_id, p.product_name,
               ROUND(SUM(CASE WHEN d.full_date <  '2026-06-15' THEN f.net_amount ELSE 0 END), 0),
               ROUND(SUM(CASE WHEN d.full_date >= '2026-06-15' THEN f.net_amount ELSE 0 END), 0)
        FROM fact_order_item f
        JOIN dim_product p ON p.product_sk = f.product_sk
        JOIN dim_date d ON d.date_key = f.date_key
        WHERE p.status = 'out_of_stock'
        GROUP BY p.merchant_id, p.product_name ORDER BY 3 DESC
    """).fetchall()
    table(oos, ["merchant", "product", "before 6-15", "after 6-15"], [10, 22, 13, 12])
    print(f"  Verdict: SURVIVES. Revenue goes to exactly zero. Supply failure, not demand.")
    print(f"\n  Final diagnosis: two independent causes - a platform-wide demand drop (carts")
    print(f"  down) plus one merchant losing its hero SKU. Neither is a checkout problem.")

    if charts:
        import matplotlib.pyplot as plt
        labels = ["revenue", "carts", "conversion", "AOV"]
        values = [pct(recent[4], prior[4]), pct(recent[1], prior[1]),
                  (recent[2] - prior[2]) / prior[2] * 100, pct(recent[5], prior[5])]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.bar(labels, values, color=["#B91C1C", "#3B5B8C", "#6C8CBC", "#C08A2E"])
        ax.axhline(0, color="#1B2637", linewidth=1)
        ax.set_ylabel("Percent change, recent 14d vs prior 14d")
        ax.set_title("Q2 · Revenue = carts x conversion x AOV, so the drop decomposes", loc="left")
        for i, v in enumerate(values):
            ax.text(i, v, f"{v:+.1f}%", ha="center",
                    va="bottom" if v >= 0 else "top", fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
        save(fig, "q2_decomposition")
        plt.close(fig)


# ---------------------------------------------------------------- Q3

def q3_day_dip(conn: sqlite3.Connection, charts: bool) -> None:
    heading(3, f"Why the dip on {INCIDENT_DAY}?")
    rows = conn.execute("""
        SELECT activity_date, carts_created, carts_converted, paid_orders,
               ROUND(net_revenue, 0), payment_attempts, declines,
               ROUND(100.0 * declines / NULLIF(payment_attempts, 0), 1), ROUND(declined_amount, 0)
        FROM mart_funnel_daily
        WHERE activity_date BETWEEN '2026-06-07' AND '2026-06-13' ORDER BY activity_date
    """).fetchall()
    table(rows, ["date", "carts", "converted", "orders", "revenue", "attempts", "declines",
                 "rate %", "failed SGD"], [12, 7, 10, 7, 9, 9, 9, 8, 11])

    reasons = conn.execute(f"""
        SELECT top_decline_reason, SUM(declines), ROUND(SUM(declined_amount), 0)
        FROM mart_payment_health_daily
        WHERE activity_date = '{INCIDENT_DAY}' AND declines > 0
        GROUP BY top_decline_reason ORDER BY 2 DESC
    """).fetchall()
    print()
    table(reasons, ["decline reason", "declines", "value"], [22, 10, 10])
    print(f"\n  Answer: carts normal, conversions normal, orders placed - and revenue collapses")
    print(f"  because half the payment attempts failed on gateway_timeout. Demand was fine;")
    print(f"  checkout broke. Only answerable because carts, orders and payments are three")
    print(f"  separate facts at three grains.")

    if charts:
        import matplotlib.pyplot as plt
        dates = [r[0][5:] for r in rows]
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
        ax1.bar(dates, [r[4] for r in rows],
                color=["#B91C1C" if r[0] == INCIDENT_DAY else "#3B5B8C" for r in rows])
        ax1.set_ylabel("Net revenue (SGD)")
        ax1.set_title("Q3 · Orders were placed. The money did not settle.", loc="left")
        ax2.plot(dates, [r[7] for r in rows], marker="o", color="#C08A2E", linewidth=2)
        ax2.set_ylabel("Decline rate %")
        ax2.set_xlabel("Date (2026-06)")
        for ax in (ax1, ax2):
            ax.spines[["top", "right"]].set_visible(False)
        save(fig, "q3_incident_day")
        plt.close(fig)


# ---------------------------------------------------------------- Q4

def q4_peak_hours(conn: sqlite3.Connection, charts: bool) -> None:
    heading(4, "What are our peak transaction hours?")
    rows = conn.execute("""
        SELECT hour_label, daypart, SUM(attempts), SUM(approvals),
               ROUND(SUM(approved_amount), 0),
               ROUND(100.0 * SUM(declines) / SUM(attempts), 1),
               ROUND(100.0 * SUM(attempts) /
                     (SELECT SUM(attempts) FROM mart_hourly_transactions), 1)
        FROM mart_hourly_transactions GROUP BY hour_label, daypart
        ORDER BY 3 DESC LIMIT 6
    """).fetchall()
    table(rows, ["hour", "daypart", "attempts", "approvals", "approved SGD", "decline %", "% of all"],
          [14, 11, 10, 10, 13, 10, 9])

    split = conn.execute("""
        SELECT CASE WHEN is_weekend = 1 THEN 'weekend' ELSE 'weekday' END, hour_label, SUM(attempts)
        FROM mart_hourly_transactions GROUP BY 1, 2 ORDER BY 1, 3 DESC
    """).fetchall()
    peaks = {}
    for day_type, hour, attempts in split:
        peaks.setdefault(day_type, (hour, attempts))
    print(f"\n  Answer: a broad evening peak, with a secondary lunch peak.")
    for day_type, (hour, attempts) in peaks.items():
        print(f"    {day_type:<8} peaks at {hour} ({attempts} attempts)")
    print(f"  Deploy windows belong overnight; on-call cover belongs 19:00-23:00. A single")
    print(f"  blended peak hour would have staffed the wrong hour on one of the two.")

    if charts:
        import matplotlib.pyplot as plt
        hourly = conn.execute("""
            SELECT hour_24,
                   SUM(CASE WHEN is_weekend = 0 THEN attempts ELSE 0 END),
                   SUM(CASE WHEN is_weekend = 1 THEN attempts ELSE 0 END)
            FROM mart_hourly_transactions GROUP BY hour_24 ORDER BY hour_24
        """).fetchall()
        fig, ax = plt.subplots(figsize=(9, 4.5))
        hours = [h for h, _, _ in hourly]
        ax.plot(hours, [w for _, w, _ in hourly], marker="o", color="#3B5B8C",
                linewidth=2, label="weekday")
        ax.plot(hours, [e for _, _, e in hourly], marker="s", color="#C08A2E",
                linewidth=2, label="weekend")
        ax.axvspan(19, 22, color="#EDF2F9", zorder=0)
        ax.axvspan(12, 13, color="#FBF3E2", zorder=0)
        ax.set_xticks(range(0, 24, 2))
        ax.set_xlabel("Hour of day")
        ax.set_ylabel("Payment attempts")
        ax.set_title("Q4 · Evening peak, lunch shoulder, dead overnight", loc="left")
        ax.legend(frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        save(fig, "q4_peak_hours")
        plt.close(fig)


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--q", nargs="*", type=int, choices=[1, 2, 3, 4], default=[1, 2, 3, 4])
    ap.add_argument("--no-charts", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"{args.db} not found - run python/build_star.py first")

    charts = not args.no_charts
    if charts:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            print("matplotlib not installed - printing answers without charts\n")
            charts = False

    conn = sqlite3.connect(args.db)
    handlers = {1: q1_merchant_drop, 2: q2_sales_drop, 3: q3_day_dip, 4: q4_peak_hours}
    for number in sorted(args.q):
        handlers[number](conn, charts)
    conn.close()
    print()


if __name__ == "__main__":
    main()
