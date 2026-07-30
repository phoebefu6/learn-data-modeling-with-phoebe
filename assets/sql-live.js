/* learn-data-modeling-with-phoebe - live SQL playground engine
   Every .sqlbox on a page is a REAL, editable SQL query run against a fresh
   copy of the Bazaar warehouse (assets/bazaar-seed.js + bazaar-star.js) entirely in your
   browser via sql.js (SQLite compiled to WebAssembly). No server, no network
   after the one-time wasm load. Edit the query, hit Run, see the result table.

   Markup a page uses:
     <div class="sqlbox" data-caption="optional line under the box" data-seed="oltp">
       <pre class="sql-src">SELECT * FROM orders LIMIT 5;</pre>
     </div>
   data-seed values:
     omitted / "star" - OLTP source PLUS the star, marts and agent views built from it
                        (bazaar-seed.js then bazaar-star.js). Slower first run, everything
                        queryable.
     "oltp"           - the eight OLTP source tables only (sessions b1-b5 live here)
     "none"           - an EMPTY database, for writing DDL from scratch */

(function () {
  var MAX_ROWS = 50;           // rows rendered before we truncate with a note
  var SQLReady = null;         // shared promise: the sql.js module, loaded once

  function loadEngine() {
    if (SQLReady) return SQLReady;
    SQLReady = new Promise(function (resolve, reject) {
      if (typeof initSqlJs !== "function") {
        reject(new Error("sql-wasm.js did not load"));
        return;
      }
      // wasm binary sits next to this script, in /assets - fully self-contained
      initSqlJs({ locateFile: function (f) { return "../assets/" + f; } })
        .then(resolve, reject);
    });
    return SQLReady;
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // render one result set (columns + values) as a table.clean
  function renderResult(res) {
    if (!res || !res.length) {
      return '<p class="sql-note">Query ran. No rows returned.</p>';
    }
    var html = "";
    res.forEach(function (r) {
      var rows = r.values;
      var shown = rows.slice(0, MAX_ROWS);
      html += '<div class="sql-tablewrap"><table class="clean sql-table"><thead><tr>';
      r.columns.forEach(function (c) { html += "<th>" + esc(c) + "</th>"; });
      html += "</tr></thead><tbody>";
      shown.forEach(function (row) {
        html += "<tr>";
        row.forEach(function (v) {
          var cell = v === null ? '<span class="sql-null">NULL</span>' : esc(v);
          html += "<td>" + cell + "</td>";
        });
        html += "</tr>";
      });
      html += "</tbody></table></div>";
      var note = rows.length + " row" + (rows.length === 1 ? "" : "s");
      if (rows.length > MAX_ROWS) note += " - showing first " + MAX_ROWS;
      html += '<p class="sql-note">' + note + "</p>";
    });
    return html;
  }

  function runQuery(SQL, seedSQL, userSQL) {
    var db = new SQL.Database();
    try {
      if (seedSQL) db.run(seedSQL);
      var res = db.exec(userSQL);
      return { ok: true, html: renderResult(res) };
    } catch (e) {
      return { ok: false, html: '<p class="sql-err">' + esc(e.message) + "</p>" };
    } finally {
      db.close();
    }
  }

  function wire(block) {
    var srcEl = block.querySelector(".sql-src");
    if (!srcEl) return;
    var original = srcEl.textContent.replace(/^\n+/, "").replace(/\s+$/, "");
    var caption = block.getAttribute("data-caption") || "";
    // an empty data-seed attribute is falsy, so read it explicitly rather than
    // relying on `attr || "star"` - that silently restores the default
    var seedMode = block.getAttribute("data-seed");
    if (seedMode === null || seedMode === "") seedMode = "star";

    block.innerHTML = "";
    block.classList.add("sqlbox-ready");

    // toolbar
    var bar = document.createElement("div");
    bar.className = "sql-bar";
    var dot = document.createElement("span"); dot.className = "sql-dot";
    var title = document.createElement("span"); title.className = "sql-title";
    title.textContent = seedMode === "none" ? "live SQL - empty database"
      : seedMode === "oltp" ? "live SQL - Bazaar source tables"
      : "live SQL - Bazaar source + star";
    var spacer = document.createElement("span"); spacer.className = "sql-spacer";
    var runBtn = document.createElement("button");
    runBtn.type = "button"; runBtn.className = "sql-btn sql-run"; runBtn.textContent = "▶ Run";
    var resetBtn = document.createElement("button");
    resetBtn.type = "button"; resetBtn.className = "sql-btn"; resetBtn.textContent = "Reset";
    var copyBtn = document.createElement("button");
    copyBtn.type = "button"; copyBtn.className = "sql-btn"; copyBtn.textContent = "Copy";
    bar.appendChild(dot); bar.appendChild(title); bar.appendChild(spacer);
    bar.appendChild(runBtn); bar.appendChild(resetBtn); bar.appendChild(copyBtn);

    // editor
    var codeWrap = document.createElement("div"); codeWrap.className = "sql-code-wrap";
    var codeLabel = document.createElement("span"); codeLabel.className = "sql-label";
    codeLabel.textContent = "You write";
    var ta = document.createElement("textarea");
    ta.className = "sql-code"; ta.spellcheck = false;
    ta.setAttribute("aria-label", "Editable SQL query");
    ta.value = original;
    var rows = Math.min(Math.max(original.split("\n").length + 1, 3), 16);
    ta.rows = rows;
    codeWrap.appendChild(codeLabel); codeWrap.appendChild(ta);

    // result
    var outWrap = document.createElement("div"); outWrap.className = "sql-out-wrap";
    var outLabel = document.createElement("span"); outLabel.className = "sql-label";
    outLabel.textContent = "Database returns";
    var out = document.createElement("div"); out.className = "sql-out";
    out.innerHTML = '<p class="sql-note sql-hint">Press ▶ Run to execute.</p>';
    outWrap.appendChild(outLabel); outWrap.appendChild(out);

    block.appendChild(bar);
    block.appendChild(codeWrap);
    block.appendChild(outWrap);
    if (caption) {
      var cap = document.createElement("div"); cap.className = "sql-cap";
      cap.textContent = caption; block.appendChild(cap);
    }

    function run() {
      out.innerHTML = '<p class="sql-note sql-hint">Running...</p>';
      loadEngine().then(function (SQL) {
        var seed = "";
        if (seedMode !== "none") seed += (window.BAZAAR_SEED || "");
        if (seedMode === "star") seed += "\n" + (window.BAZAAR_STAR_SQL || "");
        var r = runQuery(SQL, seed, ta.value);
        out.innerHTML = r.html;
        block.classList.toggle("sql-had-err", !r.ok);
      }, function (err) {
        out.innerHTML = '<p class="sql-err">Engine failed to load: ' + esc(err.message) + "</p>";
      });
    }

    runBtn.addEventListener("click", run);
    // Cmd/Ctrl+Enter runs from inside the editor
    ta.addEventListener("keydown", function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); run(); }
    });
    resetBtn.addEventListener("click", function () {
      ta.value = original;
      out.innerHTML = '<p class="sql-note sql-hint">Press ▶ Run to execute.</p>';
      block.classList.remove("sql-had-err");
    });
    copyBtn.addEventListener("click", function () {
      navigator.clipboard.writeText(ta.value).then(function () {
        copyBtn.textContent = "Copied ✓";
        setTimeout(function () { copyBtn.textContent = "Copy"; }, 1600);
      });
    });
  }

  function init() {
    var blocks = Array.prototype.slice.call(document.querySelectorAll(".sqlbox"));
    blocks.forEach(wire);
    // warm the engine in the background so the first Run feels instant
    if (blocks.length) loadEngine().catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }
})();
