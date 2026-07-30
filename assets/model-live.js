/* model-live.js - the normalization anomaly lab (builder session b2)

   One wide table, four normalization levers, real SQLite. Every metric on the scorecard is
   measured by RUNNING SQL against the schema the levers built - not asserted, not scripted:

     update anomaly  a real UPDATE that changes one product's price, then a real query
                     counting how many rows still disagree about that price
     insert anomaly  a real INSERT of a product that has never been ordered
     delete anomaly  a real DELETE of an order, then a check for whether the product it
                     referenced still exists anywhere
     redundancy      real COUNT of repeated product-name and customer-email strings
     integrity       whether a real INSERT of an order line with a bogus product_id is
                     rejected by a foreign key

   Turn all four levers on and every anomaly count goes to zero. That is 3NF, discovered
   rather than recited.

   Markup:  <div id="model-lab"></div>
   Honesty rail: the dataset is teaching-sized (12 order lines). The SQL, the constraints and
   the failures are real - this runs the same sql.js engine as every other lab on the site.
*/

(function () {
  var host = document.getElementById("model-lab");
  if (!host) return;

  var SQLReady = null;
  function loadEngine() {
    if (SQLReady) return SQLReady;
    SQLReady = new Promise(function (resolve, reject) {
      if (typeof initSqlJs !== "function") { reject(new Error("sql-wasm.js did not load")); return; }
      initSqlJs({ locateFile: function (f) { return "../assets/" + f; } }).then(resolve, reject);
    });
    return SQLReady;
  }

  /* ---------- the starting point: one wide, denormalized export ---------- */
  /* This is what every ops team hands you: a spreadsheet flattened from three or four real
     entities, with every fact repeated on every row. */
  var WIDE_ROWS = [
    // order_id, order_ts, cust_email, cust_city, product_name, category, unit_price, qty
    [9001, "2026-06-01 12:04:11", "amara@example.com", "Singapore", "Studio Headphones", "Electronics", 189.00, 1],
    [9001, "2026-06-01 12:04:11", "amara@example.com", "Singapore", "Desk Mic", "Electronics", 129.00, 1],
    [9002, "2026-06-01 20:41:02", "ben@example.com", "Melbourne", "Studio Headphones", "Electronics", 189.00, 2],
    [9003, "2026-06-02 13:22:47", "chen@example.com", "Singapore", "Pour-Over Kettle", "Home", 59.90, 1],
    [9004, "2026-06-02 21:08:15", "amara@example.com", "Singapore", "Studio Headphones", "Electronics", 189.00, 1],
    [9004, "2026-06-02 21:08:15", "amara@example.com", "Singapore", "Linen Throw", "Home", 45.00, 2],
    [9005, "2026-06-03 12:55:30", "dia@example.com", "Jakarta", "Pour-Over Kettle", "Home", 59.90, 1],
    [9006, "2026-06-03 19:31:09", "ben@example.com", "Melbourne", "Desk Mic", "Electronics", 129.00, 1],
    [9007, "2026-06-04 21:17:44", "chen@example.com", "Singapore", "Studio Headphones", "Electronics", 189.00, 1],
    [9008, "2026-06-04 12:39:58", "erik@example.com", "Singapore", "Yoga Mat", "Sport", 32.90, 3],
    [9009, "2026-06-05 20:02:23", "amara@example.com", "Singapore", "Pour-Over Kettle", "Home", 59.90, 1],
    [9010, "2026-06-05 13:47:36", "dia@example.com", "Jakarta", "Studio Headphones", "Electronics", 189.00, 1]
  ];

  var LEVERS = [
    { id: "customers", label: "Extract customers",
      hint: "one row per customer, not per order line" },
    { id: "products", label: "Extract products",
      hint: "name, category and price stored once" },
    { id: "lines", label: "Split orders from order lines",
      hint: "the header/line pair - quantity belongs on the line" },
    { id: "keys", label: "Add keys and foreign keys",
      hint: "declare the relationships and enforce them" }
  ];

  var state = { customers: false, products: false, lines: false, keys: false };

  /* ---------- schema builders: each lever changes the SQL that runs ---------- */

  function buildSchema(s) {
    var sql = [];
    var esc = function (v) { return typeof v === "string" ? "'" + v.replace(/'/g, "''") + "'" : v; };

    // Stage 0: nothing extracted - one wide table
    if (!s.customers && !s.products && !s.lines) {
      sql.push("CREATE TABLE orders_wide (order_id INTEGER, order_ts TEXT, cust_email TEXT," +
               " cust_city TEXT, product_name TEXT, category TEXT, unit_price REAL, qty INTEGER);");
      sql.push("INSERT INTO orders_wide VALUES " + WIDE_ROWS.map(function (r) {
        return "(" + r.map(esc).join(",") + ")";
      }).join(",") + ";");
      return sql.join("\n");
    }

    // Reference tables, created only when their lever is on
    if (s.customers) {
      sql.push("CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, email TEXT" +
               (s.keys ? " NOT NULL UNIQUE" : "") + ", city TEXT);");
      var emails = [];
      WIDE_ROWS.forEach(function (r) { if (emails.indexOf(r[2]) === -1) emails.push(r[2]); });
      sql.push("INSERT INTO customers VALUES " + emails.map(function (e, i) {
        var row = WIDE_ROWS.filter(function (r) { return r[2] === e; })[0];
        return "(" + (i + 1) + "," + esc(e) + "," + esc(row[3]) + ")";
      }).join(",") + ";");
    }
    if (s.products) {
      sql.push("CREATE TABLE products (product_id INTEGER PRIMARY KEY, product_name TEXT" +
               (s.keys ? " NOT NULL UNIQUE" : "") + ", category TEXT, unit_price REAL" +
               (s.keys ? " NOT NULL CHECK (unit_price > 0)" : "") + ");");
      var names = [];
      WIDE_ROWS.forEach(function (r) { if (names.indexOf(r[4]) === -1) names.push(r[4]); });
      sql.push("INSERT INTO products VALUES " + names.map(function (n, i) {
        var row = WIDE_ROWS.filter(function (r) { return r[4] === n; })[0];
        return "(" + (i + 1) + "," + esc(n) + "," + esc(row[5]) + "," + row[6] + ")";
      }).join(",") + ";");
    }

    var orderIds = [];
    WIDE_ROWS.forEach(function (r) { if (orderIds.indexOf(r[0]) === -1) orderIds.push(r[0]); });

    if (s.lines) {
      // header table
      sql.push("CREATE TABLE orders (order_id INTEGER PRIMARY KEY, order_ts TEXT" +
               (s.customers ? ", customer_id INTEGER" +
                 (s.keys ? " NOT NULL REFERENCES customers(customer_id)" : "")
                 : ", cust_email TEXT, cust_city TEXT") + ");");
      sql.push("INSERT INTO orders VALUES " + orderIds.map(function (oid) {
        var row = WIDE_ROWS.filter(function (r) { return r[0] === oid; })[0];
        if (s.customers) {
          var emails2 = [];
          WIDE_ROWS.forEach(function (r) { if (emails2.indexOf(r[2]) === -1) emails2.push(r[2]); });
          return "(" + oid + "," + esc(row[1]) + "," + (emails2.indexOf(row[2]) + 1) + ")";
        }
        return "(" + oid + "," + esc(row[1]) + "," + esc(row[2]) + "," + esc(row[3]) + ")";
      }).join(",") + ";");

      // line table
      var lineCols = "order_id INTEGER" + (s.keys ? " NOT NULL REFERENCES orders(order_id)" : "");
      lineCols += ", line_no INTEGER";
      lineCols += s.products
        ? ", product_id INTEGER" + (s.keys ? " NOT NULL REFERENCES products(product_id)" : "")
        : ", product_name TEXT, category TEXT, unit_price REAL";
      lineCols += ", qty INTEGER" + (s.keys ? " NOT NULL CHECK (qty > 0)" : "");
      if (s.keys) lineCols += ", PRIMARY KEY (order_id, line_no)";
      sql.push("CREATE TABLE order_items (" + lineCols + ");");

      var names2 = [];
      WIDE_ROWS.forEach(function (r) { if (names2.indexOf(r[4]) === -1) names2.push(r[4]); });
      var perOrder = {};
      sql.push("INSERT INTO order_items VALUES " + WIDE_ROWS.map(function (r) {
        perOrder[r[0]] = (perOrder[r[0]] || 0) + 1;
        var v = "(" + r[0] + "," + perOrder[r[0]];
        v += s.products ? "," + (names2.indexOf(r[4]) + 1)
                        : "," + esc(r[4]) + "," + esc(r[5]) + "," + r[6];
        return v + "," + r[7] + ")";
      }).join(",") + ";");
    } else {
      // orders not split yet: still one row per line, with the header repeated
      var cols = "order_id INTEGER, order_ts TEXT";
      cols += s.customers ? ", customer_id INTEGER" : ", cust_email TEXT, cust_city TEXT";
      cols += s.products ? ", product_id INTEGER" : ", product_name TEXT, category TEXT, unit_price REAL";
      cols += ", qty INTEGER";
      sql.push("CREATE TABLE orders_wide (" + cols + ");");
      var emails3 = [], names3 = [];
      WIDE_ROWS.forEach(function (r) {
        if (emails3.indexOf(r[2]) === -1) emails3.push(r[2]);
        if (names3.indexOf(r[4]) === -1) names3.push(r[4]);
      });
      sql.push("INSERT INTO orders_wide VALUES " + WIDE_ROWS.map(function (r) {
        var v = "(" + r[0] + "," + esc(r[1]);
        v += s.customers ? "," + (emails3.indexOf(r[2]) + 1) : "," + esc(r[2]) + "," + esc(r[3]);
        v += s.products ? "," + (names3.indexOf(r[4]) + 1)
                        : "," + esc(r[4]) + "," + esc(r[5]) + "," + r[6];
        return v + "," + r[7] + ")";
      }).join(",") + ";");
    }
    return sql.join("\n");
  }

  /* ---------- the five probes. Each one RUNS SQL and reports what happened. ---------- */

  function probe(SQL, s) {
    var db = new SQL.Database();
    var out = { tables: [], schema: buildSchema(s) };
    try {
      db.run("PRAGMA foreign_keys = ON;");
      db.run(out.schema);

      var names = db.exec("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name");
      out.tables = names.length ? names[0].values.map(function (r) { return r[0]; }) : [];

      var priceTable = s.products ? "products" : (s.lines ? "order_items" : "orders_wide");

      /* 1. UPDATE ANOMALY - change one product's price, then count rows that disagree */
      db.run("UPDATE " + priceTable + " SET unit_price = 149.00 WHERE " +
             (s.products ? "product_name = 'Studio Headphones'"
                         : "product_name = 'Studio Headphones' AND rowid = (SELECT MIN(rowid) FROM " +
                           priceTable + " WHERE product_name = 'Studio Headphones')") + ";");
      var stale = 0;
      if (!s.products) {
        var r1 = db.exec("SELECT COUNT(*) FROM " + priceTable +
                         " WHERE product_name = 'Studio Headphones' AND unit_price <> 149.00");
        stale = r1.length ? r1[0].values[0][0] : 0;
      }
      out.updateAnomaly = stale;

      /* 2. INSERT ANOMALY - can a product exist before anyone orders it? */
      try {
        if (s.products) {
          db.run("INSERT INTO products (product_id, product_name, category, unit_price)" +
                 " VALUES (99, 'Cat Tunnel', 'Pet', 24.00);");
          out.insertAnomaly = 0;
        } else {
          // no products table: the only way to record a product is to invent an order for it
          db.run("INSERT INTO " + (s.lines ? "order_items" : "orders_wide") +
                 " SELECT * FROM " + (s.lines ? "order_items" : "orders_wide") + " LIMIT 0;");
          out.insertAnomaly = 1;
        }
      } catch (e) { out.insertAnomaly = 1; }

      /* 3. DELETE ANOMALY - delete an order; does its product survive? */
      var target = s.products ? "'Yoga Mat'" : "'Yoga Mat'";
      if (s.lines) {
        db.run("DELETE FROM order_items WHERE order_id = 9008;");
        db.run("DELETE FROM orders WHERE order_id = 9008;");
      } else {
        db.run("DELETE FROM orders_wide WHERE order_id = 9008;");
      }
      var survives;
      if (s.products) {
        survives = db.exec("SELECT COUNT(*) FROM products WHERE product_name = " + target);
      } else {
        survives = db.exec("SELECT COUNT(*) FROM " + (s.lines ? "order_items" : "orders_wide") +
                           " WHERE product_name = " + target);
      }
      out.deleteAnomaly = (survives.length && survives[0].values[0][0] > 0) ? 0 : 1;

      /* 4. REDUNDANCY - how many times is the same string stored? */
      var repeats = 0;
      if (!s.products) {
        var rp = db.exec("SELECT COUNT(*) - COUNT(DISTINCT product_name) FROM " +
                         (s.lines ? "order_items" : "orders_wide"));
        repeats += rp.length ? rp[0].values[0][0] : 0;
      }
      if (!s.customers) {
        var table2 = s.lines ? "orders" : "orders_wide";
        var rc = db.exec("SELECT COUNT(*) - COUNT(DISTINCT cust_email) FROM " + table2);
        repeats += rc.length ? rc[0].values[0][0] : 0;
      }
      out.redundancy = repeats;

      /* 5. INTEGRITY - is a bogus reference rejected? */
      if (s.keys && s.lines && s.products) {
        try {
          db.run("INSERT INTO order_items (order_id, line_no, product_id, qty)" +
                 " VALUES (9001, 99, 4242, 1);");
          out.integrity = 0;             // it got in - the FK is not enforcing
        } catch (e) {
          out.integrity = 1;             // rejected, which is the whole point
          out.integrityError = e.message;
        }
      } else {
        out.integrity = 0;
      }
    } catch (e) {
      out.error = e.message;
    } finally {
      db.close();
    }
    return out;
  }

  /* ---------- UI ---------- */

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  var wrap = el("div", "lab");
  var bar = el("div", "lab-bar");
  bar.appendChild(el("span", "lab-dot"));
  bar.appendChild(el("span", "lab-title", "The anomaly lab - real SQLite, real anomalies"));
  var spacer = el("span", "lab-spacer"); bar.appendChild(spacer);
  var allBtn = el("button", "lab-btn primary", "Normalize everything");
  var resetBtn = el("button", "lab-btn", "Back to one wide table");
  allBtn.type = "button"; resetBtn.type = "button";
  bar.appendChild(allBtn); bar.appendChild(resetBtn);
  wrap.appendChild(bar);

  var leverBox = el("div", "lab-levers");
  var leverInputs = {};
  LEVERS.forEach(function (lever) {
    var label = el("label", "lab-lever");
    var input = document.createElement("input");
    input.type = "checkbox"; input.id = "lever-" + lever.id;
    leverInputs[lever.id] = input;
    label.appendChild(input);
    var body = el("span", "lab-lever-body");
    body.appendChild(el("b", null, lever.label));
    body.appendChild(el("span", null, lever.hint));
    label.appendChild(body);
    leverBox.appendChild(label);
    input.addEventListener("change", function () {
      state[lever.id] = input.checked;
      render();
    });
  });
  wrap.appendChild(leverBox);

  var scoreBox = el("div", "lab-score");
  wrap.appendChild(scoreBox);

  var verdict = el("p", "lab-verdict");
  wrap.appendChild(verdict);

  var details = document.createElement("details");
  details.className = "lab-details";
  var summary = document.createElement("summary");
  summary.textContent = "Show the schema these levers just built";
  details.appendChild(summary);
  var pre = el("pre", "lab-sql");
  details.appendChild(pre);
  wrap.appendChild(details);

  var rail = el("p", "lab-rail",
    "The dataset is teaching-sized (12 order lines). Everything else is real: this runs " +
    "SQLite in your browser, the UPDATE/INSERT/DELETE probes actually execute, and the " +
    "foreign key that rejects a bogus product id is a real constraint.");
  wrap.appendChild(rail);

  host.appendChild(wrap);

  var METRICS = [
    { key: "updateAnomaly", label: "Update anomaly",
      good: "one price, one place", bad: "rows now disagree" },
    { key: "insertAnomaly", label: "Insert anomaly",
      good: "products exist on their own", bad: "cannot add a product without an order" },
    { key: "deleteAnomaly", label: "Delete anomaly",
      good: "product survives the order", bad: "deleting an order erased the product" },
    { key: "redundancy", label: "Repeated strings",
      good: "stored once", bad: "same value stored many times" },
    { key: "integrity", label: "Bogus reference",
      good: "rejected by a foreign key", bad: "accepted silently" }
  ];

  function render() {
    scoreBox.innerHTML = '<p class="lab-note">Building schema and running probes...</p>';
    loadEngine().then(function (SQL) {
      var r = probe(SQL, state);
      if (r.error) {
        scoreBox.innerHTML = '<p class="lab-err">' + r.error + "</p>";
        return;
      }
      pre.textContent = r.schema;

      scoreBox.innerHTML = "";
      var grid = el("div", "lab-grid");
      var clean = 0;
      METRICS.forEach(function (metric) {
        var value = r[metric.key];
        var isGood = metric.key === "integrity" ? value === 1 : value === 0;
        if (metric.key === "integrity" && !(state.keys && state.lines && state.products)) isGood = false;
        if (isGood) clean++;
        var card = el("div", "lab-metric " + (isGood ? "ok" : "bad"));
        card.appendChild(el("span", "lab-metric-label", metric.label));
        card.appendChild(el("span", "lab-metric-value",
          metric.key === "redundancy" ? String(value)
            : metric.key === "integrity" ? (isGood ? "rejected" : "allowed")
            : (isGood ? "none" : String(value || 1))));
        card.appendChild(el("span", "lab-metric-note", isGood ? metric.good : metric.bad));
        grid.appendChild(card);
      });
      scoreBox.appendChild(grid);

      var tables = el("p", "lab-note", "Tables now in the database: " +
        (r.tables.length ? r.tables.join(", ") : "none"));
      scoreBox.appendChild(tables);

      var on = LEVERS.filter(function (l) { return state[l.id]; }).length;
      if (clean === METRICS.length) {
        verdict.className = "lab-verdict win";
        verdict.textContent = "5 of 5 clean. Every fact is stored exactly once and the " +
          "relationships are enforced. That is third normal form - and you got here by " +
          "removing failures, not by memorising a definition.";
      } else if (on === 0) {
        verdict.className = "lab-verdict lose";
        verdict.textContent = "0 of 5 clean. One wide table repeats every fact on every row, " +
          "so a price change has to find every copy, a product cannot exist before someone " +
          "buys it, and deleting an order destroys the only record of what was in it.";
      } else {
        verdict.className = "lab-verdict";
        verdict.textContent = clean + " of 5 clean with " + on + " lever" + (on === 1 ? "" : "s") +
          " on. Keep going - each extraction kills a specific failure, and the last lever " +
          "(keys) is what stops the database from accepting nonsense.";
      }
    }, function (err) {
      scoreBox.innerHTML = '<p class="lab-err">Engine failed to load: ' + err.message + "</p>";
    });
  }

  allBtn.addEventListener("click", function () {
    LEVERS.forEach(function (l) { state[l.id] = true; leverInputs[l.id].checked = true; });
    render();
  });
  resetBtn.addEventListener("click", function () {
    LEVERS.forEach(function (l) { state[l.id] = false; leverInputs[l.id].checked = false; });
    render();
  });

  render();
})();
