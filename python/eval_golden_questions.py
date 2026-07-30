"""Score the model as an agent substrate: 20 golden questions, execution-match grading (b9).

This is the scorecard behind session b9's live lab. For each question in
semantic/golden_questions.jsonl it runs the candidate SQL and the grounded SQL and compares
the RESULT SETS, not the query text - two correct queries can look nothing alike.

Three modes, which are the lab's three rungs:

    --mode grounded   the query a model writes WITH the schema card + metric definitions
    --mode naive      the query a model writes WITHOUT them (the recorded failure per item)
    --mode live       call Claude for real, with or without the contract (--no-contract)

Usage:
    python python/eval_golden_questions.py                       # grounded, offline
    python python/eval_golden_questions.py --mode naive          # watch accuracy collapse
    python python/eval_golden_questions.py --mode live --no-contract
    python python/eval_golden_questions.py --mode naive --show-sql
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "bazaar.db"
GOLDEN = ROOT / "semantic" / "golden_questions.jsonl"

TOLERANCE = 0.01     # money compares to the cent; anything closer is float noise


def load_questions() -> list[dict]:
    return [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]


def execute(conn: sqlite3.Connection, sql: str):
    try:
        return conn.execute(sql).fetchall(), None
    except sqlite3.Error as exc:
        return None, str(exc)


def results_match(expected, actual) -> bool:
    """Execution match: same shape, same values, floats to the cent."""
    if expected is None or actual is None:
        return False
    if len(expected) != len(actual):
        return False
    for row_e, row_a in zip(expected, actual):
        if len(row_e) != len(row_a):
            return False
        for value_e, value_a in zip(row_e, row_a):
            if isinstance(value_e, float) or isinstance(value_a, float):
                if value_e is None or value_a is None:
                    if value_e is not value_a:
                        return False
                elif abs(float(value_e) - float(value_a)) > TOLERANCE:
                    return False
            elif value_e != value_a:
                return False
    return True


def live_sql(question: str, use_contract: bool, conn: sqlite3.Connection) -> tuple[str, str | None]:
    """Ask Claude for one SQL statement. Returns (sql, error)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from agent_text_to_sql import (  # local import so offline runs need no SDK
        RUN_SQL_TOOL, SCHEMA_CARD, SYSTEM_WITH_CONTRACT, SYSTEM_WITHOUT_CONTRACT,
        load_metrics, MODEL,
    )
    import anthropic

    system = (SYSTEM_WITH_CONTRACT.format(schema_card=SCHEMA_CARD.read_text(),
                                          metrics=load_metrics(conn))
              if use_contract else SYSTEM_WITHOUT_CONTRACT)
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL, max_tokens=2048, system=system,
        tools=[RUN_SQL_TOOL],
        tool_choice={"type": "tool", "name": "run_sql"},   # we want the SQL, not prose
        messages=[{"role": "user", "content": question}],
    )
    if response.stop_reason == "refusal":
        return "", "model declined"
    for block in response.content:
        if block.type == "tool_use":
            return block.input["sql"], None
    return "", "model returned no SQL"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--mode", choices=["grounded", "naive", "live"], default="grounded")
    ap.add_argument("--no-contract", action="store_true",
                    help="live mode only: withhold the schema card")
    ap.add_argument("--show-sql", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"{args.db} not found - run python/build_star.py first", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    questions = load_questions()

    label = args.mode
    if args.mode == "live":
        label = f"live, contract {'OFF' if args.no_contract else 'ON'}"
    print(f"Bazaar golden set - {len(questions)} questions, mode: {label}\n")

    correct, wrong, errored = 0, [], []
    for q in questions:
        expected, expected_error = execute(conn, q["sql"])
        if expected_error:
            print(f"  {q['id']}  GOLDEN QUERY BROKEN: {expected_error}")
            errored.append(q["id"])
            continue

        if args.mode == "grounded":
            candidate = q["sql"]
        elif args.mode == "naive":
            candidate = q["naive_sql"]
        else:
            candidate, error = live_sql(q["question"], not args.no_contract, conn)
            if error:
                print(f"  {q['id']}  ERROR  {error}")
                errored.append(q["id"])
                continue

        actual, actual_error = execute(conn, candidate)
        if actual_error:
            print(f"  {q['id']}  ERROR  {actual_error}")
            errored.append(q["id"])
            if args.show_sql:
                print(f"         sql: {candidate}")
            continue

        if results_match(expected, actual):
            correct += 1
            print(f"  {q['id']}  PASS   {q['question'][:62]}")
        else:
            wrong.append(q)
            print(f"  {q['id']}  WRONG  {q['question'][:62]}")
            print(f"         expected {str(expected[:1])[:56]}")
            print(f"         got      {str(actual[:1])[:56]}")
            if args.mode == "naive":
                print(f"         cause    {q['naive_error']}")
            if args.show_sql:
                print(f"         sql      {candidate}")

    conn.close()
    total = len(questions)
    accuracy = 100.0 * correct / total
    print(f"\n{'-' * 68}")
    print(f"accuracy  {correct}/{total} = {accuracy:.0f}%    wrong {len(wrong)}    errored {len(errored)}")

    if args.mode == "naive":
        print("\nEvery failure above is a modeling failure, not a model failure: line-vs-order")
        print("grain, an averaged average, a rate with no denominator, a fact-to-fact join. The")
        print("schema card and v_metric_definitions are what remove them - run --mode grounded")
        print("to see the same 20 questions at 100%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
