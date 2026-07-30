# Source map - learn-data-modeling-with-phoebe

What this course teaches, where each idea comes from, and what it deliberately does not cover.
Written before the pages, so coverage is a design decision rather than an afterthought.

## The 80% bar

Each session teaches roughly 80% of the working content of its mapped sources - the part you
use on a Tuesday. Formal proofs, vendor-specific tuning, and certification material stay with
the originals, and every page says so.

## Position in the deng ladder

This course is the **prequel to `learn-sql`**. The Daybreak database that `learn-sql` hands you
to query, and that `learn-data-warehouse` loads, is a schema somebody designed - this is the
course where that design work happens, on a marketplace of its own.

```
learn-data-modeling  ->  learn-sql  ->  learn-data-warehouse  ->  learn-data-engineering
   design the schema     query it       operate it as a warehouse   build the pipelines
```

The overlap with `learn-data-warehouse` is deliberate and bounded. That course covers star
schemas from the operator's side: staging layers, SCD load mechanics, marts, the lakehouse,
cost. This course covers them from the designer's side - grain, additivity, key strategy,
conformance - and ships the DDL, the transform, the marts and the agent layer as runnable
files. Roughly 15% of the concept surface is shared; the deliverables do not overlap at all.

## Primary sources

| Source | What we take from it | Where |
|--------|---------------------|-------|
| Kimball & Ross, *The Data Warehouse Toolkit* (3rd ed) | dimensional modeling: grain, conformed dimensions, fact types (transaction / periodic / accumulating), additivity, degenerate and junk dimensions, SCD types 0-3, the bus matrix | b5, b6, b7, b10, a3 |
| Inmon, *Building the Data Warehouse* | the normalized-core / dimensional-mart split, and why the argument between the two schools is really about who owns change | b5, a1, a3 |
| Codd's relational papers + any standard database text | functional dependency, 1NF / 2NF / 3NF / BCNF, the three anomaly classes | b2, b3 |
| ANSI SQL + PostgreSQL and SQLite documentation | constraint semantics (PRIMARY KEY, UNIQUE, FOREIGN KEY, CHECK, NOT NULL), type choices, index basics, the difference between a declared and an enforced constraint | b4, b5 |
| Linstedt & Olschimke, *Building a Scalable Data Warehouse with Data Vault 2.0* | hubs / links / satellites, and an honest account of when the complexity is worth it | b8 (comparison only) |
| dbt documentation (staging / intermediate / marts layering, model contracts, tests) | the modern layering convention and the idea of a model contract as an enforced artifact | b8, b9, a4 |
| Zhamak Dehghani, *Data Mesh* | domain ownership of models, data as a product, the contract as the interface | a3, a5 |
| Fowler / Evans on modeling (*PoEAA*, *Domain-Driven Design*) | conceptual -> logical -> physical as three distinct artifacts; the ubiquitous-language argument for naming | b1, a5 |
| Anthropic tool-use and structured-output documentation | how a model actually consumes a schema: tool definitions, read-only guardrails, the schema-as-prompt framing | b9 |
| Published text-to-SQL benchmark practice (Spider / BIRD-style execution-match grading) | grading generated SQL by comparing RESULT SETS rather than query text, and why exec-match is the honest metric | b9 |

**Re-verify before delivery:** the dbt layering docs and the Anthropic API surface both move.
Check the current dbt "How we structure our dbt projects" guide and the tool-use docs before
teaching from the specifics in b8/b9. Everything else on this list is stable canon.

## Session coverage

Legend: ✓ taught to the 80% bar · ◐ touched, pointer given · - out of scope by design

### Leader track (6 x 45 min)

| # | Session | Kimball | Inmon | Normalization | Contracts / mesh | Tooling | Agent-readiness |
|---|---------|---------|-------|---------------|------------------|---------|-----------------|
| a1 | Why the schema decides everything | ◐ | ◐ | ◐ | - | - | ◐ |
| a2 | The cost of a bad model | ◐ | - | ◐ | ◐ | - | - |
| a3 | Grain, and one number one meaning | ✓ | ✓ | - | ✓ | - | ◐ |
| a4 | The tooling landscape | - | - | - | ◐ | ✓ | ◐ |
| a5 | Naming standards and ownership | - | - | - | ✓ | ◐ | ◐ |
| a6 | Agent-ready data | - | - | - | ✓ | ◐ | ✓ |

### Builder track (10 x 45 min)

| # | Session | Normalization | Keys / constraints | Dimensional | Physical | Agent | Ships |
|---|---------|---------------|--------------------|-------------|----------|-------|-------|
| b1 | Bazaar's source reality | ◐ | - | - | - | - | conceptual model |
| b2 | The anomaly lab | ✓ | ◐ | - | - | - | `model-live.js` lab |
| b3 | ER, cardinality, keys | ✓ | ✓ | - | ◐ | - | ER diagram |
| b4 | Physical OLTP | ◐ | ✓ | - | ✓ | - | `sql/01`, `gen_bazaar_data.py` |
| b5 | Why analysts cannot query OLTP | ◐ | - | ✓ | ◐ | - | grain worksheet |
| b6 | Dimension design | - | ✓ | ✓ | ◐ | - | `sql/10` |
| b7 | Fact design | - | ◐ | ✓ | ◐ | - | `sql/11`, `sql/12` |
| b8 | Answering the four questions | - | - | ✓ | ◐ | ◐ | `sql/20`, `sql/30`, `answer_questions.py` |
| b9 | Agent-ready modeling | - | - | ◐ | - | ✓ | `sql/40`, `semantic/*`, `agent-live.js`, 3 agent scripts |
| b10 | Capstone: returns and refunds | ✓ | ✓ | ✓ | ✓ | ✓ | new subject area, `validate_model.py` green |

## Not covered, by design

- **Formal normalization beyond 3NF.** BCNF, 4NF and 5NF get a paragraph and a pointer in b3.
  Almost no production schema is designed past 3NF on purpose, and the ones that need it have a
  specialist in the room.
- **Data Vault as a build.** b8 compares it honestly and says when it earns its complexity.
  Building one is a course of its own.
- **Warehouse load mechanics.** Incremental loads, MERGE, and applying a type-2 change on every
  run belong to `learn-data-warehouse` (builder sessions 4-6). This course designs the SCD2
  structure and loads it once.
- **Pipelines and orchestration.** `learn-data-engineering` and `learn-dataops`.
- **Query tuning.** Index internals, execution plans, partitioning strategy. b5 covers only the
  indexes the access paths obviously need.
- **Graph and document modeling.** Mentioned in b8's pattern comparison; each is its own topic.
- **Prompt engineering.** b9 is about what the MODEL must publish for an agent to be accurate.
  Prompt craft is `learn-prompt-engineering`; retrieval is `learn-rag`; the text-to-SQL
  application layer is `learn-text-to-sql`.

## The running case: Bazaar

A multi-merchant ecommerce marketplace. Eight OLTP tables, 90 days of generated-but-deterministic
data (seed 42), and four stories buried in it that sessions b8 and b9 make you find:

1. Merchant M07 (Nimbus Audio) loses 85% of its revenue in the final fortnight.
2. A checkout incident on 2026-06-10 declines 9 of 17 payment attempts that day.
3. Transaction volume peaks 19:00-22:59, with a lunch shoulder at 12:00-13:59.
4. A paid-search budget cut on 2026-06-18 drops cart volume ~22%.

Two independent causes behind one revenue drop is the point: a model that cannot separate them
sends the room to the wrong team. A marketplace was chosen over a single retailer specifically
so that "which merchant dropped" is a question the model has to be able to answer.

Every number quoted on every page comes from running the shipped code. Regenerate with
`python python/gen_bazaar_data.py && python python/build_star.py --fresh` and they will match.

## Verified facts used on the pages

- `fact_order_item` 1,434 rows · `fact_transaction` 1,060 · `fact_cart` 2,229 · six dimensions
- net revenue on settled lines: 111,906.48 SGD · AOV 116.93 · 957 settled orders
- cart conversion 44.19% · overall decline rate 6.2%
- M07: 3,063 -> 455 SGD across the two 14-day windows (-85.2%), and its hero product's revenue
  goes to exactly 0 after 2026-06-15
- 2026-06-10: 17 attempts, 9 declines (52.9%), 740 SGD of failed money, reason `gateway_timeout`
- golden-set execution-match accuracy: 0/20 without the semantic contract, 20/20 with it
- `validate_model.py`: 27 checks, all passing, 0% unknown-member rate on every fact
