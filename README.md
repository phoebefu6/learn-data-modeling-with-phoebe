# learn data modeling with phoebe

Design the schema everything else queries. A two-track, 16-session course that takes a
multi-merchant ecommerce marketplace from a flat spreadsheet export to a governed dimensional
model an AI analyst can query accurately - and ships every artifact as runnable code.

**Live course:** https://phoebefu6.github.io/learn-data-modeling-with-phoebe/

- **Leader track** (6 x 45 min, no code): why the schema decides every argument about numbers,
  what a bad model costs, grain and one-number-one-meaning, the tooling landscape, naming and
  ownership, and what to fund for agent-ready data.
- **Builder track** (10 x 45 min, live SQLite in your browser): entities, normalization, keys,
  DDL, six dimensions, three facts, four marts, a semantic layer, and a capstone that takes a
  brand-new subject area down the whole ladder.

Two signature labs run real SQLite compiled to WebAssembly, entirely in your tab:

- **The anomaly lab** (session b2) - four normalization levers rebuild the schema, then real
  UPDATE, INSERT and DELETE probes measure which anomalies survive. All four levers on, all
  five probes clean: third normal form derived rather than recited.
- **The agent-readiness lab** (session b9) - the same 20 business questions answered with and
  without the semantic contract, graded by execution match. 0 out of 20 without it, 20 out of
  20 with it.

## The running project: Bazaar

A multi-merchant marketplace. 12 merchants, 60 products, 60 shoppers, 90 days
(2026-04-01 to 2026-06-29), deterministic on seed 42 so every number printed on the course
pages is reproducible. Four stories are buried in the data on purpose, and sessions b8 and b9
make you find them:

1. Merchant M07 loses 85% of its revenue in the final fortnight.
2. A checkout incident on 2026-06-10 declines 9 of 17 payment attempts that day.
3. Transaction volume peaks 19:00-22:59, with a lunch shoulder at 12:00-13:59.
4. A paid-search budget cut on 2026-06-18 drops cart volume about 22%.

Two independent causes behind one revenue drop is the point: a model that cannot separate them
sends the room to the wrong team.

## Run the code

Python 3.10+. The core pipeline needs no third-party packages at all.

```bash
python python/gen_bazaar_data.py --rows      # generate the source data (seed 42)
python python/build_star.py --fresh          # OLTP -> star -> marts -> agent views
python python/validate_model.py              # 27 checks, exits non-zero on failure
python python/answer_questions.py            # the four business questions + charts at 300 DPI
```

Charts need `matplotlib`; the two agent scripts and `eval_golden_questions.py --mode live` need
`anthropic` (`pip install -r python/requirements.txt`). Everything else is standard library.

```bash
python python/eval_golden_questions.py                    # grounded: 20/20
python python/eval_golden_questions.py --mode naive       # ungrounded: 0/20, with the cause of each failure
python python/agent_text_to_sql.py --offline "what are our peak transaction hours?"
python python/agent_query_to_text.py --golden q14         # narration with the caveat attached
```

`--offline` runs without an API key, which is how the course pages exercise it. Drop `--offline`
to run the real loop: schema card as the system prompt, one strict `run_sql` tool, a read-only
allowlist guard, results fed back until the model answers.

After editing anything in `sql/` or `semantic/`, regenerate the browser assets so the page labs
and the local scripts stay in sync:

```bash
python python/build_browser_assets.py
```

## Repository layout

```
sql/
  01_oltp_ddl.sql          the transactional schema, commented as the lesson (b3-b5)
  02_seed.sql              generated source data, data only
  10_dim_ddl.sql           six dimensions, four rules, SCD2 where history matters (b6)
  11_fact_ddl.sql          three facts, three grains, measure discipline (b7)
  12_oltp_to_star.sql      the full-refresh load, one modeling decision per INSERT (b6-b7)
  20_marts.sql             four marts at four grains (b8)
  30_business_questions.sql the four questions, with the verified answers in comments (b8)
  40_agent_views.sql       five governed views + the metric-definitions table (b9)
python/
  gen_bazaar_data.py       deterministic generator -> CSVs, sql/02, assets/bazaar-seed.js
  build_star.py            runs the SQL in order into bazaar.db
  validate_model.py        27 checks: grain, keys, integrity, SCD2, additivity, reconciliation
  answer_questions.py      the four analyses + PNG/SVG charts
  agent_text_to_sql.py     English question -> SQL -> rows -> answer, with guardrails
  agent_query_to_text.py   result set -> sentence, narrated from the model's own metadata
  eval_golden_questions.py execution-match scorecard over the golden set
  build_browser_assets.py  regenerates the in-browser SQL and golden-set assets
semantic/
  schema_card.md           the prompt: five views, their grains, six hard rules
  contract.yaml            owner, SLO, allowed and forbidden joins, metrics, synonyms, limits
  golden_questions.jsonl   20 questions, each with the grounded SQL and the recorded failure
materials/
  official-course-map.md   source map, per-session coverage, honest out-of-scope list
courses/                   16 session pages
assets/                    style.css, app.js, mindmap.js, sql.js engine, the two labs
data/                      generated CSVs
```

## Where this sits

This is the prerequisite the data-engineering ladder was missing:

```
learn-data-modeling  ->  learn-sql  ->  learn-data-warehouse  ->  learn-data-engineering
   design the schema     query it       operate it                build the pipelines
```

The schema [learn-sql-with-phoebe](https://phoebefu6.github.io/learn-sql-with-phoebe/) hands you
to query is a schema somebody designed - this is where that work happens. Warehouse load
mechanics (incremental loads, applying type-2 changes on every run) belong to
[learn-data-warehouse-with-phoebe](https://phoebefu6.github.io/learn-data-warehouse-with-phoebe/);
pipelines belong to
[learn-data-engineering-with-phoebe](https://phoebefu6.github.io/learn-data-engineering-with-phoebe/).

## Sources

Built from Kimball & Ross (*The Data Warehouse Toolkit*), Inmon (*Building the Data Warehouse*),
relational-theory fundamentals, the ANSI SQL / PostgreSQL / SQLite constraint documentation, the
dbt layering and model-contract conventions, Dehghani (*Data Mesh*), and published text-to-SQL
benchmark practice. Full mapping, including what is deliberately out of scope, in
[materials/official-course-map.md](materials/official-course-map.md).

by Phoebe Fu · part of [Learn with Phoebe](https://phoebefu6.github.io/learn-with-phoebe/)
