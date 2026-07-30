"""Ask Bazaar a question in English; get SQL, real rows, and a plain-English answer (b9).

This is the payoff of the whole course: the model you designed is what makes an AI agent
accurate. The agent gets three things and nothing else -

    1. semantic/schema_card.md   the five views, their grains, and the hard rules
    2. v_metric_definitions      every metric's definition, expression, grain and caveat
    3. one tool, run_sql         read-only, allowlisted to the agent views

...and the guardrails below reject anything outside that box before it touches the database.
Every rule maps to a modeling decision from sessions b6-b8. Remove the schema card and the
same model writes confident, wrong SQL: it counts lines as orders, averages an average, and
joins two facts at different grains. That is the point of session b9's lab.

Usage:
    python python/agent_text_to_sql.py "which merchant dropped the most last fortnight?"
    python python/agent_text_to_sql.py --offline "what are our peak transaction hours?"
    python python/agent_text_to_sql.py --no-contract "how many orders in June?"   # see it fail

--offline answers from semantic/golden_questions.jsonl with no API call, so the lesson runs
without a key. --no-contract withholds the schema card and metric definitions, which is the
lever session b9 asks you to toggle.

Needs ANTHROPIC_API_KEY (or `ant auth login`) unless you pass --offline.
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
SCHEMA_CARD = ROOT / "semantic" / "schema_card.md"
GOLDEN = ROOT / "semantic" / "golden_questions.jsonl"

MODEL = "claude-opus-5"
MAX_TURNS = 6

# The agent may read these and nothing else. A model cannot misuse a table it cannot reach -
# removing the footgun beats prompting the agent not to pull the trigger.
ALLOWED_OBJECTS = {
    "v_sales_line", "v_payment_attempt", "v_cart",
    "v_merchant_day", "v_hour_of_day", "v_metric_definitions",
}

FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|pragma|vacuum)\b", re.I
)
OBJECT_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.I)

RUN_SQL_TOOL = {
    "name": "run_sql",
    "description": (
        "Run one read-only SELECT against Bazaar's analytical views and return the rows. "
        "Only the views listed in the schema card are readable. Call this once you have a "
        "query; if it returns an error, read the error and try again."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "A single SELECT or WITH statement."},
            "rationale": {
                "type": "string",
                "description": "One sentence on why this query answers the question at the right grain.",
            },
        },
        "required": ["sql", "rationale"],
        "additionalProperties": False,
    },
}

SYSTEM_WITH_CONTRACT = """You are Bazaar's analytics agent. You answer business questions by \
writing SQL against a governed set of views, running it, and reporting the number.

Work in this order, every time:
1. Read the schema card below and pick the ONE view whose grain matches the question.
2. Check v_metric_definitions for any metric the question names before defining it yourself.
3. Write the SQL, call run_sql, read the rows.
4. Answer in two or three sentences. State the number, the period, and the denominator of any
   rate. Then show the SQL you ran.

If a question needs an object or a join the schema card does not permit, say so and explain \
what is missing instead of guessing.

--- SCHEMA CARD ---
{schema_card}
--- METRIC DEFINITIONS ---
{metrics}
"""

SYSTEM_WITHOUT_CONTRACT = """You are Bazaar's analytics agent. Answer business questions by \
writing SQL and running it with the run_sql tool.

The database is a SQLite ecommerce marketplace warehouse. Explore it however you like and \
answer the question with a number.
"""


# ---------------------------------------------------------------- the tool

def guard(sql: str) -> str | None:
    """Return an error string if this SQL must not run. None means it is allowed."""
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        return "Rejected: one statement per call."
    if not re.match(r"^(select|with)\b", stripped, re.I):
        return "Rejected: read-only access. The query must start with SELECT or WITH."
    if FORBIDDEN_SQL.search(stripped):
        return "Rejected: read-only access. No DDL or DML."
    referenced = {m.lower() for m in OBJECT_REF.findall(stripped)}
    # CTE names are legal referents, so subtract anything defined in a WITH clause
    cte_names = {m.lower() for m in re.findall(r"(?:with|,)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(",
                                               stripped, re.I)}
    illegal = sorted(referenced - ALLOWED_OBJECTS - cte_names)
    if illegal:
        return (f"Rejected: {', '.join(illegal)} is not readable. Allowed views: "
                f"{', '.join(sorted(ALLOWED_OBJECTS))}.")
    return None


def run_sql(conn: sqlite3.Connection, sql: str, max_rows: int = 40) -> str:
    error = guard(sql)
    if error:
        return error
    try:
        cursor = conn.execute(sql)
    except sqlite3.Error as exc:
        return f"SQL error: {exc}"
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchmany(max_rows)
    if not rows:
        return "0 rows."
    lines = [" | ".join(columns)]
    lines += [" | ".join("NULL" if v is None else str(v) for v in row) for row in rows]
    more = cursor.fetchone()
    if more:
        lines.append(f"... truncated at {max_rows} rows")
    return "\n".join(lines)


def load_metrics(conn: sqlite3.Connection) -> str:
    rows = conn.execute("""
        SELECT metric_name, definition, sql_expression, source_view, grain, caveat
        FROM v_metric_definitions ORDER BY metric_name
    """).fetchall()
    return "\n".join(
        f"- {name}: {definition}\n  expression: {expr}\n  from: {view} (grain: {grain})"
        f"\n  caveat: {caveat}"
        for name, definition, expr, view, grain, caveat in rows
    )


# ---------------------------------------------------------------- offline mode

def offline_answer(conn: sqlite3.Connection, question: str, use_contract: bool) -> int:
    """No API call: look the question up in the golden set and run the canned SQL.

    With the contract on, we run the grounded query. With it off, we run the `naive_sql` an
    ungrounded model actually writes for that question - the failure is real, not asserted.
    """
    entries = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    words = set(re.findall(r"[a-z]+", question.lower()))
    scored = sorted(
        entries,
        key=lambda e: len(words & set(re.findall(r"[a-z]+", e["question"].lower()))),
        reverse=True,
    )
    best = scored[0]
    overlap = len(words & set(re.findall(r"[a-z]+", best["question"].lower())))
    if overlap < 2:
        print("Offline mode only answers the 20 questions in semantic/golden_questions.jsonl.")
        print("Closest match was too weak. Run without --offline for open questions.")
        return 1

    sql = best["sql"] if use_contract else best["naive_sql"]
    print(f"[offline] matched golden question {best['id']}: {best['question']}")
    print(f"[offline] semantic contract: {'ON' if use_contract else 'OFF'}\n")
    print("SQL the agent runs:\n")
    print("  " + sql.replace("\n", "\n  "))
    print("\nRows:\n")
    print("  " + run_sql(conn, sql).replace("\n", "\n  "))
    if not use_contract:
        print(f"\nWhat went wrong: {best['naive_error']}")
        print("Grounded answer for comparison:\n")
        print("  " + run_sql(conn, best["sql"]).replace("\n", "\n  "))
    return 0


# ---------------------------------------------------------------- live mode

def live_answer(conn: sqlite3.Connection, question: str, use_contract: bool) -> int:
    try:
        import anthropic
    except ImportError:
        print("pip install anthropic, or pass --offline", file=sys.stderr)
        return 1

    client = anthropic.Anthropic()

    if use_contract:
        system = SYSTEM_WITH_CONTRACT.format(
            schema_card=SCHEMA_CARD.read_text(), metrics=load_metrics(conn)
        )
    else:
        system = SYSTEM_WITHOUT_CONTRACT

    messages: list[dict] = [{"role": "user", "content": question}]

    for _ in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            tools=[RUN_SQL_TOOL],
            messages=messages,
        )

        if response.stop_reason == "refusal":
            print("The model declined this request.", file=sys.stderr)
            return 1

        for block in response.content:
            if block.type == "text" and block.text.strip():
                print(block.text)

        if response.stop_reason != "tool_use":
            return 0

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            sql = block.input["sql"]
            print(f"\n  [tool] {block.input.get('rationale', '')}")
            print("  [sql]  " + sql.replace("\n", "\n         "))
            output = run_sql(conn, sql)
            print("  [rows] " + output.replace("\n", "\n         ") + "\n")
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                "is_error": output.startswith(("Rejected:", "SQL error:")),
            })
        messages.append({"role": "user", "content": results})

    print(f"Stopped after {MAX_TURNS} turns without a final answer.", file=sys.stderr)
    return 1


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", help="a business question in plain English")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--offline", action="store_true", help="no API call; use the golden set")
    ap.add_argument("--no-contract", action="store_true",
                    help="withhold the schema card and metric definitions")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"{args.db} not found - run python/build_star.py first", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)   # read-only at the driver too
    use_contract = not args.no_contract
    try:
        if args.offline:
            return offline_answer(conn, args.question, use_contract)
        return live_answer(conn, args.question, use_contract)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
