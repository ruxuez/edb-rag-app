// ---------- tabs ----------
function activateTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tabName));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === tabName));
  if (tabName === "overview") refreshStatus();
}
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});
document.querySelectorAll("[data-goto-tab]").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.gotoTab));
});

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ---------- overview ----------
async function refreshStatus() {
  const dbEl = document.getElementById("status-db");
  const extEl = document.getElementById("status-extensions");
  const fbEl = document.getElementById("status-feedback-rows");
  const catEl = document.getElementById("status-catalog-files");
  const tbody = document.querySelector("#status-pipelines tbody");
  dbEl.textContent = "checking…";
  dbEl.className = "value";
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    dbEl.textContent = data.db_connected ? "Connected" : "Not connected";
    dbEl.className = "value " + (data.db_connected ? "ok" : "err");
    extEl.textContent = data.extensions.length ? data.extensions.join(", ") : "none yet";
    fbEl.textContent = data.feedback_rows === null ? "—" : data.feedback_rows;
    catEl.textContent = data.catalog_files === null ? "—" : data.catalog_files;
    tbody.innerHTML = "";
    if (!data.pipelines.length) {
      tbody.innerHTML = '<tr><td colspan="4" style="color:var(--dim)">No pipelines yet — run Setup.</td></tr>';
    } else {
      for (const p of data.pipelines) {
        const tr = document.createElement("tr");
        const modeClass = p.auto_processing === "Live" ? "live" : p.auto_processing === "Background" ? "background" : "disabled";
        tr.innerHTML = `<td class="mono">${esc(p.name)}</td><td class="mono">${esc(p.source)}</td><td class="mono">${esc(p.destination)}</td><td><span class="badge ${modeClass}">${esc(p.auto_processing)}</span></td>`;
        tbody.appendChild(tr);
      }
    }
  } catch (e) {
    dbEl.textContent = "Error: " + e.message;
    dbEl.className = "value err";
  }
}
document.getElementById("refresh-status").addEventListener("click", refreshStatus);
refreshStatus();

// ---------- overview: create database ----------
function actionCardHtml(info, runLabel) {
  const why = info.why ? `<div class="step-why"><strong>Why:</strong> ${esc(info.why)}</div>` : "";
  return `
    <div class="step-hdr">
      <span class="step-n">DB</span>
      <div class="step-titles">
        <h3>${esc(info.title)}</h3>
        <div class="d">${esc(info.description)}</div>
      </div>
      <button class="runbtn" data-run>${esc(runLabel)}</button>
    </div>
    <div class="step-body">
      ${why}
      <div class="sql-label">SQL <span class="sql-tag preview" data-sql-tag>preview</span></div>
      <div class="sql-block" data-sql></div>
      <div class="output-wrap" data-output-wrap>
        <div class="sql-label">Output</div>
        <div class="output-block" data-output></div>
      </div>
    </div>
  `;
}

async function initCreateDatabaseCard() {
  const container = document.getElementById("overview-create-database");
  let info;
  try {
    const res = await fetch("/api/overview/create-database");
    info = await res.json();
  } catch (e) {
    container.textContent = "Failed to load: " + e.message;
    return;
  }
  const card = document.createElement("div");
  card.className = "step";
  card.innerHTML = actionCardHtml(info, "▶ Create database");
  container.appendChild(card);

  const sqlEl = card.querySelector("[data-sql]");
  renderSql(sqlEl, info.sql);

  const btn = card.querySelector("[data-run]");
  const tagEl = card.querySelector("[data-sql-tag]");
  const outWrap = card.querySelector("[data-output-wrap]");
  const outEl = card.querySelector("[data-output]");

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const originalLabel = btn.textContent;
    btn.innerHTML = '<span class="spinner"></span> Running…';
    outWrap.classList.add("show");
    outEl.className = "output-block";
    outEl.textContent = "Running…";
    try {
      const res = await fetch("/api/overview/create-database", { method: "POST" });
      const data = await res.json();
      renderSql(sqlEl, data.sql.length ? data.sql : info.sql);
      tagEl.textContent = "executed";
      tagEl.classList.remove("preview");
      tagEl.classList.add("executed");
      outEl.textContent = data.output + (data.error ? "\nError: " + data.error : "");
      outEl.classList.add(data.ok ? "ok" : "err");
      refreshStatus();
    } catch (e) {
      outEl.textContent = "Request failed: " + e.message;
      outEl.classList.add("err");
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  });
}
initCreateDatabaseCard();

// ---------- setup steps ----------
function renderSql(container, statements, query) {
  if (!statements || !statements.length) {
    container.textContent = "(no SQL — this step doesn't touch the database)";
    return;
  }
  container.innerHTML = statements
    .map((s) => {
      const text = query != null ? s.replaceAll("{query}", query) : s;
      return `<div class="stmt">${esc(text.trim())}</div>`;
    })
    .join("");
}

function stepCardHtml(step) {
  const queryRow = step.needs_query
    ? `<div class="query-row">
         <input type="text" data-query value="${esc(step.default_query || "")}" placeholder="Query text..." />
       </div>`
    : "";
  const extra = step.id === "seed-catalog-pdf" ? '<div class="inspect-extra" data-inspect-extra></div>' : "";
  const why = step.why ? `<div class="step-why"><strong>Why:</strong> ${esc(step.why)}</div>` : "";
  return `
    <div class="step-hdr">
      <span class="step-n">${step.n}</span>
      <div class="step-titles">
        <h3>${esc(step.title)}</h3>
        <div class="d">${esc(step.description)}</div>
      </div>
      <button class="runbtn" data-run>▶ Run</button>
    </div>
    <div class="step-body">
      ${why}
      ${queryRow}
      <div class="sql-label">SQL <span class="sql-tag preview" data-sql-tag>preview</span></div>
      <div class="sql-block" data-sql></div>
      ${extra}
      <div class="output-wrap" data-output-wrap>
        <div class="sql-label">Output</div>
        <div class="output-block" data-output></div>
      </div>
    </div>
  `;
}

function reinitializeCardHtml(reinit) {
  return `
    <div class="step-hdr">
      <span class="step-n">⟳</span>
      <div class="step-titles">
        <h3>${esc(reinit.title)}</h3>
        <div class="d">${esc(reinit.description)}</div>
      </div>
      <button class="runbtn danger" data-run>Reinitialize</button>
    </div>
    <div class="step-body">
      <div class="sql-label">SQL <span class="sql-tag preview" data-sql-tag>preview</span></div>
      <div class="sql-block" data-sql></div>
      <div class="output-wrap" data-output-wrap>
        <div class="sql-label">Output</div>
        <div class="output-block" data-output></div>
      </div>
    </div>
  `;
}

function initReinitializeCard(reinit) {
  const container = document.getElementById("setup-reinitialize");
  const card = document.createElement("div");
  card.className = "step danger";
  card.innerHTML = reinitializeCardHtml(reinit);
  container.appendChild(card);

  const sqlEl = card.querySelector("[data-sql]");
  renderSql(sqlEl, reinit.sql);

  const btn = card.querySelector("[data-run]");
  const tagEl = card.querySelector("[data-sql-tag]");
  const outWrap = card.querySelector("[data-output-wrap]");
  const outEl = card.querySelector("[data-output]");

  btn.addEventListener("click", async () => {
    if (!confirm("Drop aidb/pgfs and every pipeline-created table? customer_feedback and the uploaded catalog PDF(s) are kept.")) {
      return;
    }
    btn.disabled = true;
    const originalLabel = btn.textContent;
    btn.innerHTML = '<span class="spinner"></span> Reinitializing…';
    outWrap.classList.add("show");
    outEl.className = "output-block";
    outEl.textContent = "Running…";
    try {
      const res = await fetch("/api/setup/reinitialize", { method: "POST" });
      const data = await res.json();
      renderSql(sqlEl, data.sql.length ? data.sql : reinit.sql);
      tagEl.textContent = "executed";
      tagEl.classList.remove("preview");
      tagEl.classList.add("executed");
      outEl.textContent = data.output + (data.error ? "\nError: " + data.error : "");
      outEl.classList.add(data.ok ? "ok" : "err");
      if (data.ok) {
        // DB state underneath every step card just changed — reload so
        // each one re-fetches a fresh preview and clears its stale
        // "executed" output instead of showing results that no longer hold.
        setTimeout(() => location.reload(), 1200);
      }
    } catch (e) {
      outEl.textContent = "Request failed: " + e.message;
      outEl.classList.add("err");
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  });
}

async function initSetupSteps() {
  const container = document.getElementById("setup-steps");
  let steps = [];
  let reinit = null;
  try {
    const res = await fetch("/api/setup/steps");
    const data = await res.json();
    steps = data.steps;
    reinit = data.reinitialize;
  } catch (e) {
    container.textContent = "Failed to load setup steps: " + e.message;
    return;
  }
  if (reinit) initReinitializeCard(reinit);

  for (const step of steps) {
    const card = document.createElement("div");
    card.className = "step";
    card.dataset.step = step.id;
    card.innerHTML = stepCardHtml(step);
    container.appendChild(card);

    const sqlEl = card.querySelector("[data-sql]");
    const queryInput = card.querySelector("[data-query]");
    const currentQuery = () => (queryInput ? queryInput.value : null);
    renderSql(sqlEl, step.sql, currentQuery());
    if (queryInput) {
      queryInput.addEventListener("input", () => {
        const tag = card.querySelector("[data-sql-tag]");
        if (tag.textContent === "preview") renderSql(sqlEl, step.sql, currentQuery());
      });
    }

    const btn = card.querySelector("[data-run]");
    const tagEl = card.querySelector("[data-sql-tag]");
    const outWrap = card.querySelector("[data-output-wrap]");
    const outEl = card.querySelector("[data-output]");
    const extraEl = card.querySelector("[data-inspect-extra]");

    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const originalLabel = btn.textContent;
      btn.innerHTML = '<span class="spinner"></span> Running…';
      outWrap.classList.add("show");
      outEl.className = "output-block";
      outEl.textContent = "Running…";
      try {
        const body = step.needs_query ? JSON.stringify({ query: currentQuery() }) : undefined;
        const headers = step.needs_query ? { "Content-Type": "application/json" } : undefined;
        const res = await fetch(`/api/setup/${step.id}`, { method: "POST", body, headers });
        const data = await res.json();
        renderSql(sqlEl, data.sql.length ? data.sql : step.sql, currentQuery());
        tagEl.textContent = "executed";
        tagEl.classList.remove("preview");
        tagEl.classList.add("executed");
        outEl.textContent = data.output + (data.error ? "\nError: " + data.error : "");
        outEl.classList.add(data.ok ? "ok" : "err");
        if (step.id === "seed-catalog-pdf" && data.ok) {
          extraEl.innerHTML = `<div class="sql-label">Catalog PDF</div>
            <iframe class="pdf-frame" src="/api/catalog-pdf/acme_product_catalog.pdf"></iframe>`;
        }
        if (step.id === "register-completions-model" && data.ok) {
          document.getElementById("setup-next-banner").style.display = "block";
        }
        refreshStatus();
      } catch (e) {
        outEl.textContent = "Request failed: " + e.message;
        outEl.classList.add("err");
      } finally {
        btn.disabled = false;
        btn.textContent = originalLabel;
      }
    });
  }
}
initSetupSteps();

// ---------- sql console ----------
function renderSqlResult(container, data) {
  if (!data.ok) {
    container.innerHTML = `<div class="output-block err">${esc(data.error)}</div>`;
    return;
  }
  if (!data.columns.length) {
    container.innerHTML = `<div class="output-block ok">OK${data.rowcount != null ? ` (${data.rowcount} row(s) affected)` : ""}</div>`;
    return;
  }
  if (!data.rows.length) {
    container.innerHTML = `<div class="output-block">0 rows</div>`;
    return;
  }
  const thead = `<tr>${data.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>`;
  const tbody = data.rows
    .map((row) => `<tr>${row.map((v) => `<td>${v === null ? "<em>null</em>" : esc(v)}</td>`).join("")}</tr>`)
    .join("");
  container.innerHTML = `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
}

const sqlInput = document.getElementById("sql-input");
const sqlRunBtn = document.getElementById("sql-run-btn");
const sqlResult = document.getElementById("sql-result");

async function runSql() {
  const query = sqlInput.value.trim();
  if (!query) return;
  sqlRunBtn.disabled = true;
  const originalLabel = sqlRunBtn.textContent;
  sqlRunBtn.innerHTML = '<span class="spinner"></span> Running…';
  sqlResult.innerHTML = '<div class="output-block">Running…</div>';
  try {
    const res = await fetch("/api/sql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql: query }),
    });
    const data = await res.json();
    renderSqlResult(sqlResult, data);
    refreshStatus();
  } catch (e) {
    sqlResult.innerHTML = `<div class="output-block err">Request failed: ${esc(e.message)}</div>`;
  } finally {
    sqlRunBtn.disabled = false;
    sqlRunBtn.textContent = originalLabel;
  }
}
sqlRunBtn.addEventListener("click", runSql);
sqlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    runSql();
  }
});

// ---------- chat ----------
const chatLog = document.getElementById("chat-log");
const chatInput = document.getElementById("chat-input");
const chatSend = document.getElementById("chat-send");

// Minimal, dependency-free markdown: bold, italics, inline code, and
// paragraphs/bullet lists. Good enough for the plain-prose answers this
// demo's completions model returns.
function renderMarkdown(text) {
  const lines = esc(text).split("\n");
  let html = "";
  let inList = false;
  for (const raw of lines) {
    const line = raw.trim();
    const isBullet = /^[-*]\s+/.test(line);
    if (isBullet) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inlineMd(line.replace(/^[-*]\s+/, ""))}</li>`;
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      if (line) html += `<p>${inlineMd(line)}</p>`;
    }
  }
  if (inList) html += "</ul>";
  return html || `<p>${inlineMd(esc(text))}</p>`;
}
function inlineMd(s) {
  return s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");
}

function appendMessage(role, text) {
  const row = document.createElement("div");
  row.className = `msg-row ${role}`;
  const avatar = document.createElement("div");
  avatar.className = `avatar ${role}`;
  avatar.textContent = role === "user" ? "You" : "AI";
  const body = document.createElement("div");
  body.className = "msg-body";
  if (role === "bot") {
    body.innerHTML = renderMarkdown(text);
  } else {
    body.textContent = text;
  }
  row.appendChild(avatar);
  row.appendChild(body);
  chatLog.appendChild(row);
  chatLog.scrollTop = chatLog.scrollHeight;
  return body;
}

function appendTyping() {
  const row = document.createElement("div");
  row.className = "msg-row bot";
  row.innerHTML = `<div class="avatar bot">AI</div><div class="msg-body"><div class="typing-dots"><span></span><span></span><span></span></div></div>`;
  chatLog.appendChild(row);
  chatLog.scrollTop = chatLog.scrollHeight;
  return row;
}

async function sendMessage() {
  const message = chatInput.value.trim();
  if (!message) return;
  appendMessage("user", message);
  chatInput.value = "";
  autoResize();
  chatSend.disabled = true;
  const typingRow = appendTyping();
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, topk: 20 }),
    });
    const data = await res.json();
    typingRow.remove();
    appendMessage("bot", data.answer || `Error: ${data.error || "unknown"}`);
  } catch (e) {
    typingRow.remove();
    appendMessage("bot", "Request failed: " + e.message);
  } finally {
    chatSend.disabled = false;
    chatInput.focus();
  }
}

function autoResize() {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + "px";
}
chatInput.addEventListener("input", autoResize);
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
chatSend.addEventListener("click", sendMessage);

appendMessage("bot", "Hi! I'm ACME Bank's assistant. Ask me about our products or customer feedback.");

document.querySelectorAll(".suggestion-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    chatInput.value = btn.dataset.q;
    autoResize();
    sendMessage();
  });
});

// ---------- upload ----------
function revealInspectCard() {
  document.getElementById("upload-inspect-card").style.display = "block";
}

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("upload-input");
  const out = document.getElementById("upload-output");
  if (!input.files.length) return;
  const formData = new FormData();
  formData.append("file", input.files[0]);
  out.className = "output-block";
  out.textContent = "Uploading…";
  try {
    const res = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await res.json();
    out.textContent = data.ok ? `Uploaded to ${data.key}` : `Error: ${data.error || "unknown"}`;
    out.classList.add(data.ok ? "ok" : "err");
    if (data.ok) revealInspectCard();
  } catch (err) {
    out.textContent = "Request failed: " + err.message;
    out.classList.add("err");
  }
});

document.getElementById("upload-sample-btn").addEventListener("click", async () => {
  const out = document.getElementById("upload-output");
  out.className = "output-block";
  out.textContent = "Uploading bundled sample…";
  try {
    const res = await fetch("/api/upload-sample", { method: "POST" });
    const data = await res.json();
    out.textContent = data.ok ? `Uploaded ${data.filename} to ${data.key}` : `Error: ${data.error || "unknown"}`;
    out.classList.add(data.ok ? "ok" : "err");
    if (data.ok) revealInspectCard();
  } catch (err) {
    out.textContent = "Request failed: " + err.message;
    out.classList.add("err");
  }
});

document.querySelectorAll("[data-inspect]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const kind = btn.dataset.inspect; // "volume-content" | "pipeline-metrics"
    const out = document.getElementById(kind === "volume-content" ? "inspect-volume-output" : "inspect-metrics-output");
    btn.disabled = true;
    const originalLabel = btn.textContent;
    btn.innerHTML = '<span class="spinner"></span> Running…';
    out.className = "output-block";
    out.textContent = "Running…";
    try {
      const res = await fetch(`/api/inspect/${kind}`, { method: "POST" });
      const data = await res.json();
      out.textContent = data.output + (data.error ? "\nError: " + data.error : "");
      out.classList.add(data.ok ? "ok" : "err");
      if (kind === "pipeline-metrics" && data.ok) {
        const match = data.output.match(/catalogs_pipeline'[^}]*'count\(source records\)': (\d+)/);
        const hint = document.getElementById("inspect-metrics-hint");
        if (match && parseInt(match[1], 10) >= 2) {
          hint.style.display = "block";
        }
      }
    } catch (e) {
      out.textContent = "Request failed: " + e.message;
      out.classList.add("err");
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  });
});

document.getElementById("insert-feedback-btn").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  const out = document.getElementById("insert-feedback-output");
  btn.disabled = true;
  const originalLabel = btn.textContent;
  btn.innerHTML = '<span class="spinner"></span> Running…';
  out.className = "output-block";
  out.textContent = "Running…";
  try {
    const res = await fetch("/api/inspect/insert-feedback", { method: "POST" });
    const data = await res.json();
    out.textContent = data.output + (data.error ? "\nError: " + data.error : "");
    out.classList.add(data.ok ? "ok" : "err");
    refreshStatus();
  } catch (err) {
    out.textContent = "Request failed: " + err.message;
    out.classList.add("err");
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
});
