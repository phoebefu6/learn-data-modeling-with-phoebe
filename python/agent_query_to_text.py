"""Query-to-text: turn a result set into a sentence a human can act on (session b9).

Text-to-SQL is half the loop. The other half is narration - and narration is where a badly
modeled result set gets dangerous, because a fluent sentence hides a wrong number. This script
narrates deterministically from the model's own metadata:

  * column NAMES tell it what each measure is (net_revenue, attempts, decline_rate_pct)
  * v_metric_definitions tells it the definition, the grain, and the CAVEAT
  * any column ending in _pct or _rate gets its denominator demanded, not assumed

The caveat is the part that matters. "Decline rate was 18.2%" is true and useless on eleven
attempts; "18.2% of 11 attempts - below the 30-attempt floor, treat as noise" is an answer.

Usage:
    python python/agent_query_to_text.py --golden q03
    python python/agent_query_to_text.py --sql "SELECT ... FROM v_sales_line ..."
    python python/agent_query_to_text.py --golden q14 --llm     # Claude writes the prose
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "bazaar.db"
GOLDEN = ROOT / "semantic" / "golden_questions.jsonl"

MODEL = "claude-opus-5"
SMALL_SAMPLE_FLOOR = 30      # matches the rule in semantic/schema_card.md

MONEY_HINTS = ("revenue", "amount", "value", "margin", "commission", "aov", "discount")
RATE_HINTS = ("_pct", "_rate", "rate_")
COUNT_HINTS = ("attempts", "orders", "declines", "approvals", "units", "carts",
               "conversions", "count")


def classify(column: str) -> str:
    name = column.lower()
    if any(h in name for h in RATE_HINTS):
        return "rate"
    if any(h in name for h in MONEY_HINTS):
        return "money"
    if any(h in name for h in COUNT_HINTS):
        return "count"
    if "date" in name or "hour" in name or "month" in name or "day" in name:
        return "time"
    return "label"


def fmt(value, kind: str) -> str:
    if value is None:
        return "no value"
    if kind == "money" and isinstance(value, (int, float)):
        return f"{value:,.2f} SGD"
    if kind == "rate" and isinstance(value, (int, float)):
        return f"{value:.1f}%"
    if kind == "count" and isinstance(value, (int, float)):
        return f"{value:,.0f}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def load_caveats(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        name: caveat
        for name, caveat in conn.execute(
            "SELECT metric_name, caveat FROM v_metric_definitions"
        ).fetchall()
    }


def narrate(columns: list[str], rows: list[tuple], caveats: dict[str, str]) -> str:
    kinds = [classify(c) for c in columns]
    lines: list[str] = []

    if not rows:
        return "The query returned no rows. Either the filter excluded everything or the period has no data."

    # a single row, single column: the classic "one number" answer
    if len(rows) == 1 and len(columns) == 1:
        lines.append(f"{columns[0].replace('_', ' ')}: {fmt(rows[0][0], kinds[0])}.")
    elif len(rows) == 1:
        parts = [f"{c.replace('_', ' ')} {fmt(v, k)}" for c, v, k in zip(columns, rows[0], kinds)]
        lines.append("Result: " + ", ".join(parts) + ".")
    else:
        label_idx = next((i for i, k in enumerate(kinds) if k in ("label", "time")), 0)
        measure_idx = next((i for i, k in enumerate(kinds) if k in ("money", "count", "rate")),
                           len(columns) - 1)
        top = rows[0]
        lines.append(
            f"{len(rows)} rows. Top by {columns[measure_idx].replace('_', ' ')}: "
            f"{top[label_idx]} at {fmt(top[measure_idx], kinds[measure_idx])}."
        )
        if len(rows) > 1:
            last = rows[-1]
            lines.append(
                f"Lowest shown: {last[label_idx]} at {fmt(last[measure_idx], kinds[measure_idx])}."
            )

    # rates: demand a denominator, and flag small samples honestly
    for i, (column, kind) in enumerate(zip(columns, kinds)):
        if kind != "rate":
            continue
        denominator_idx = next(
            (j for j, (c, k) in enumerate(zip(columns, kinds))
             if k == "count" and "decline" not in c.lower()), None
        )
        if denominator_idx is None:
            lines.append(
                f"Caution: {column} is a rate with no denominator in this result. Re-run the "
                f"query with its count so the reader can judge whether it is signal."
            )
        else:
            worst = min(r[denominator_idx] for r in rows if r[denominator_idx] is not None)
            if worst < SMALL_SAMPLE_FLOOR:
                lines.append(
                    f"Caution: some rows have as few as {worst:,.0f} "
                    f"{columns[denominator_idx].replace('_', ' ')}. Below "
                    f"{SMALL_SAMPLE_FLOOR}, {column} is noise, not a ranking."
                )

    # surface the contract's own caveat for any metric the result names
    for column in columns:
        for metric, caveat in caveats.items():
            if metric in column.lower() and caveat.lower() != "none.":
                lines.append(f"Definition caveat ({metric}): {caveat}")
                break

    return "\n".join(lines)


def llm_narrate(question: str, sql: str, columns: list[str], rows: list[tuple],
                deterministic: str) -> int:
    try:
        import anthropic
    except ImportError:
        print("pip install anthropic, or drop --llm", file=sys.stderr)
        return 1

    table = " | ".join(columns) + "\n" + "\n".join(
        " | ".join("NULL" if v is None else str(v) for v in row) for row in rows[:25]
    )
    prompt = f"""Write the answer a marketplace analyst would give.

Question: {question or "(none supplied - describe what the result shows)"}
SQL that produced it:
{sql}

Result:
{table}

Facts the model's own metadata already established - do not contradict these, and keep any
caution they raise:
{deterministic}

Rules: two or three sentences. Lead with the number and its period. Always state the
denominator of any rate. If a caution above applies, say it plainly rather than softening it.
Do not add analysis the result does not support."""

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL, max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        print("The model declined this request.", file=sys.stderr)
        return 1
    for block in response.content:
        if block.type == "text":
            print(block.text)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--sql", help="the query to narrate")
    group.add_argument("--golden", help="a question id from semantic/golden_questions.jsonl")
    ap.add_argument("--llm", action="store_true", help="have Claude write the prose")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"{args.db} not found - run python/build_star.py first", file=sys.stderr)
        return 1

    question = ""
    sql = args.sql
    if args.golden:
        entries = {
            json.loads(line)["id"]: json.loads(line)
            for line in GOLDEN.read_text().splitlines() if line.strip()
        }
        if args.golden not in entries:
            print(f"unknown id {args.golden}; have {', '.join(entries)}", file=sys.stderr)
            return 1
        question = entries[args.golden]["question"]
        sql = entries[args.golden]["sql"]

    if re.match(r"^\s*(insert|update|delete|drop|alter|create)\b", sql or "", re.I):
        print("read-only: SELECT or WITH only", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    cursor = conn.execute(sql)
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    caveats = load_caveats(conn)
    conn.close()

    if question:
        print(f"Question: {question}\n")
    print("SQL:")
    print("  " + sql.replace("\n", "\n  ") + "\n")
    deterministic = narrate(columns, rows, caveats)
    print("Narration (deterministic, from the model's own metadata):")
    print("  " + deterministic.replace("\n", "\n  "))

    if args.llm:
        print("\nNarration (Claude, grounded on the facts above):")
        return llm_narrate(question, sql, columns, rows, deterministic)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
