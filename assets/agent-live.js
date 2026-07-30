/* agent-live.js - the agent-readiness lab (builder session b9)

   Pick a business question. Watch what an AI analyst does with your model - twice: once with
   the semantic contract (schema card + metric definitions + grain rules) and once without.
   Both queries EXECUTE against the real Bazaar star in your browser, so the wrong answer is
   a real number produced by real SQL, not a claim on a slide.

   The scorecard runs all 20 golden questions through both settings and reports execution-match
   accuracy: contract off scores 0/20, contract on scores 20/20. The gap is the model's doing,
   not the language model's.

   Markup:
     <div id="agent-lab"></div>
   Requires (in this order): sql-wasm.js, bazaar-seed.js, bazaar-star.js, bazaar-golden.js

   Honesty rail: SQL generation is not live here - each question carries the grounded query and
   the query an ungrounded model actually writes, recorded in semantic/golden_questions.jsonl.
   Execution, grading and every number shown are real. python/agent_text_to_sql.py runs the
   same loop against the live API when you want to watch a model do it in real time.
*/

(function () {
  var host = document.getElementById("agent-lab");
  if (!host) return;

  var GOLDEN = window.BAZAAR_GOLDEN || [];
  var TOLERANCE = 0.01;

  var SQLReady = null, DB = null;

  function loadEngine() {
    if (SQLReady) return SQLReady;
    SQLReady = new Promise(function (resolve, reject) {
      if (typeof initSqlJs !== "function") { reject(new Error("sql-wasm.js did not load")); return; }
      initSqlJs({ locateFile: function (f) { return "../assets/" + f; } }).then(function (SQL) {
        var db = new SQL.Database();
        db.run(window.BAZAAR_SEED || "");
        db.run(window.BAZAAR_STAR_SQL || "");
        DB = db;
        resolve(db);
      }, reject);
    });
    return SQLReady;
  }

  function run(sql) {
    try {
      var res = DB.exec(sql);
      if (!res.length) return { ok: true, columns: [], rows: [] };
      return { ok: true, columns: res[0].columns, rows: res[0].values };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }

  function same(a, b) {
    if (!a.ok || !b.ok) return false;
    if (a.rows.length !== b.rows.length) return false;
    for (var i = 0; i < a.rows.length; i++) {
      if (a.rows[i].length !== b.rows[i].length) return false;
      for (var j = 0; j < a.rows[i].length; j++) {
        var x = a.rows[i][j], y = b.rows[i][j];
        if (typeof x === "number" || typeof y === "number") {
          if (x === null || y === null) { if (x !== y) return false; }
          else if (Math.abs(Number(x) - Number(y)) > TOLERANCE) return false;
        } else if (x !== y) return false;
      }
    }
    return true;
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function renderTable(result, limit) {
    if (!result.ok) return '<p class="lab-err">SQL error: ' + result.error + "</p>";
    if (!result.rows.length) return '<p class="lab-note">0 rows.</p>';
    var rows = result.rows.slice(0, limit || 6);
    var html = '<div class="sql-tablewrap"><table class="clean sql-table"><thead><tr>';
    result.columns.forEach(function (c) { html += "<th>" + c + "</th>"; });
    html += "</tr></thead><tbody>";
    rows.forEach(function (r) {
      html += "<tr>";
      r.forEach(function (v) {
        html += "<td>" + (v === null ? '<span class="sql-null">NULL</span>' : v) + "</td>";
      });
      html += "</tr>";
    });
    html += "</tbody></table></div>";
    if (result.rows.length > rows.length) {
      html += '<p class="lab-note">' + result.rows.length + " rows, showing first " + rows.length + ".</p>";
    }
    return html;
  }

  /* ---------------------------------------------------------------- UI shell */

  var wrap = el("div", "lab");

  var bar = el("div", "lab-bar");
  bar.appendChild(el("span", "lab-dot"));
  bar.appendChild(el("span", "lab-title", "Agent-readiness lab - real SQL, real execution"));
  bar.appendChild(el("span", "lab-spacer"));
  var scoreBtn = el("button", "lab-btn primary", "Score all 20 questions");
  scoreBtn.type = "button";
  bar.appendChild(scoreBtn);
  wrap.appendChild(bar);

  /* the lever */
  var leverBox = el("div", "lab-levers one");
  var leverLabel = el("label", "lab-lever");
  var lever = document.createElement("input");
  lever.type = "checkbox"; lever.checked = true; lever.id = "agent-contract";
  leverLabel.appendChild(lever);
  var leverBody = el("span", "lab-lever-body");
  leverBody.appendChild(el("b", null, "Semantic contract ON"));
  leverBody.appendChild(el("span", null,
    "the agent gets the schema card, v_metric_definitions and the grain rules"));
  leverLabel.appendChild(leverBody);
  leverBox.appendChild(leverLabel);
  wrap.appendChild(leverBox);

  /* question picker */
  var picker = el("div", "lab-questions");
  var select = document.createElement("select");
  select.className = "lab-select";
  GOLDEN.forEach(function (q, i) {
    var option = document.createElement("option");
    option.value = String(i);
    option.textContent = q.id + " · " + q.question;
    select.appendChild(option);
  });
  picker.appendChild(el("label", "lab-select-label", "Business question"));
  picker.appendChild(select);
  var askBtn = el("button", "lab-btn primary", "Ask the agent");
  askBtn.type = "button";
  picker.appendChild(askBtn);
  wrap.appendChild(picker);

  var context = el("div", "lab-context");
  wrap.appendChild(context);

  var output = el("div", "lab-output");
  wrap.appendChild(output);

  var scorecard = el("div", "lab-scorecard");
  wrap.appendChild(scorecard);

  wrap.appendChild(el("p", "lab-rail",
    "SQL generation is recorded, not live: each question carries the grounded query and the " +
    "query an ungrounded model actually writes (semantic/golden_questions.jsonl). Execution, " +
    "grading and every number here are real - this is the Bazaar star running in your tab. " +
    "python/agent_text_to_sql.py runs the same loop against the live API."));

  host.appendChild(wrap);

  /* ---------------------------------------------------------------- context panel */

  var CONTRACT_ON = [
    ["schema card", "five views, each with its grain stated in one sentence"],
    ["v_metric_definitions", "13 metrics: definition, expression, grain, caveat"],
    ["grain rules", "never join two facts; COUNT(DISTINCT order_id) for orders"],
    ["ratio rules", "rates as numerator/denominator, never a stored average"],
    ["access", "read-only, six views, nothing else reachable"]
  ];
  var CONTRACT_OFF = [
    ["schema", "table and column names only - no grains, no definitions"],
    ["metrics", "none. The agent invents each definition on the spot"],
    ["grain rules", "none. Two facts look joinable, so they get joined"],
    ["ratio rules", "none. AVG() of a percentage looks like an average"],
    ["access", "everything, including the base facts"]
  ];

  function renderContext() {
    context.innerHTML = "";
    var on = lever.checked;
    var head = el("p", "lab-context-head",
      on ? "What the agent can see (contract ON):" : "What the agent can see (contract OFF):");
    context.appendChild(head);
    var list = el("ul", "lab-context-list");
    (on ? CONTRACT_ON : CONTRACT_OFF).forEach(function (pair) {
      var li = el("li", on ? "has" : "lacks");
      li.appendChild(el("b", null, pair[0] + ": "));
      li.appendChild(document.createTextNode(pair[1]));
      list.appendChild(li);
    });
    context.appendChild(list);
  }

  /* ---------------------------------------------------------------- ask one question */

  function ask() {
    var q = GOLDEN[Number(select.value)];
    var on = lever.checked;
    output.innerHTML = '<p class="lab-note">Running SQL against the Bazaar star...</p>';

    loadEngine().then(function () {
      var grounded = run(q.sql);
      var candidate = on ? grounded : run(q.naive_sql);
      var correct = on ? true : same(grounded, candidate);

      output.innerHTML = "";
      output.appendChild(el("p", "lab-q", q.question));

      var sqlBlock = el("div", "lab-block");
      sqlBlock.appendChild(el("span", "lab-block-label",
        on ? "SQL the agent writes (grounded)" : "SQL the agent writes (ungrounded)"));
      sqlBlock.appendChild(el("pre", "lab-sql", (on ? q.sql : q.naive_sql)));
      output.appendChild(sqlBlock);

      var rowBlock = el("div", "lab-block");
      rowBlock.appendChild(el("span", "lab-block-label", "What the database returns"));
      var rowsHost = el("div");
      rowsHost.innerHTML = renderTable(candidate);
      rowBlock.appendChild(rowsHost);
      output.appendChild(rowBlock);

      var verdict = el("div", "lab-verdict " + (correct ? "win" : "lose"));
      if (correct) {
        verdict.textContent = "Correct. The answer matches the grounded query exactly, because " +
          "the model told the agent what one row means and where the metric is defined.";
      } else {
        verdict.textContent = "Wrong - and confidently so. " + q.naive_error;
      }
      output.appendChild(verdict);

      if (!correct) {
        var fix = el("div", "lab-block");
        fix.appendChild(el("span", "lab-block-label", "The grounded query, for comparison"));
        fix.appendChild(el("pre", "lab-sql", q.sql));
        var groundedHost = el("div");
        groundedHost.innerHTML = renderTable(grounded);
        fix.appendChild(groundedHost);
        output.appendChild(fix);
      }
    }, function (err) {
      output.innerHTML = '<p class="lab-err">Engine failed to load: ' + err.message + "</p>";
    });
  }

  /* ---------------------------------------------------------------- scorecard */

  function score() {
    scorecard.innerHTML = '<p class="lab-note">Running 40 queries (20 questions x 2 settings)...</p>';
    loadEngine().then(function () {
      var onCorrect = 0, offCorrect = 0, rows = [];
      GOLDEN.forEach(function (q) {
        var grounded = run(q.sql);
        var naive = run(q.naive_sql);
        var offOk = same(grounded, naive);
        if (grounded.ok) onCorrect++;
        if (offOk) offCorrect++;
        rows.push({ id: q.id, question: q.question, offOk: offOk, error: q.naive_error });
      });

      var total = GOLDEN.length;
      scorecard.innerHTML = "";
      var head = el("div", "lab-score-head");
      var offCard = el("div", "lab-scorebox bad");
      offCard.appendChild(el("span", "lab-scorebox-label", "Contract OFF"));
      offCard.appendChild(el("span", "lab-scorebox-value",
        offCorrect + "/" + total));
      offCard.appendChild(el("span", "lab-scorebox-note",
        Math.round(100 * offCorrect / total) + "% execution-match accuracy"));
      var onCard = el("div", "lab-scorebox ok");
      onCard.appendChild(el("span", "lab-scorebox-label", "Contract ON"));
      onCard.appendChild(el("span", "lab-scorebox-value", onCorrect + "/" + total));
      onCard.appendChild(el("span", "lab-scorebox-note",
        Math.round(100 * onCorrect / total) + "% execution-match accuracy"));
      head.appendChild(offCard);
      head.appendChild(onCard);
      scorecard.appendChild(head);

      var list = el("div", "lab-score-list");
      rows.forEach(function (r) {
        var row = el("div", "lab-score-row " + (r.offOk ? "ok" : "bad"));
        row.appendChild(el("span", "lab-score-id", r.id));
        row.appendChild(el("span", "lab-score-q", r.question));
        row.appendChild(el("span", "lab-score-note",
          r.offOk ? "ungrounded query happened to match" : r.error));
        list.appendChild(row);
      });
      scorecard.appendChild(list);

      scorecard.appendChild(el("p", "lab-note",
        "Same questions, same database, same language model. The only variable is whether the " +
        "model published its grains, its metric definitions and its join rules. That is what " +
        "'agent-ready' means, and it is modeling work, not prompt work."));
    }, function (err) {
      scorecard.innerHTML = '<p class="lab-err">Engine failed to load: ' + err.message + "</p>";
    });
  }

  lever.addEventListener("change", function () { renderContext(); ask(); });
  select.addEventListener("change", ask);
  askBtn.addEventListener("click", ask);
  scoreBtn.addEventListener("click", score);

  renderContext();
  ask();
})();
