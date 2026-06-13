// HITL inbox (ADR-022, Baustein 2b): list pending pipeline decisions and resolve
// them. Talks to Pilot's /inbox + /inbox/{id}/resolve, which proxy to
// script-runner -> lobster. The page renders the gate's prompt + response schema
// + subject context, and turns a decision into a resume call.

const INBOX_DEMO_PIPELINE = "/data/openclaw/workspace/demo-input.lobster";

async function initInbox() {
  if (!document.getElementById("inbox-list")) return;
  const refresh = document.getElementById("inbox-refresh");
  if (refresh) refresh.addEventListener("click", refreshInbox);
  const demo = document.getElementById("inbox-demo");
  if (demo) demo.addEventListener("click", runInboxDemo);
  await refreshInbox();
}

function inboxMsg(text) {
  return '<div style="color:var(--tx-muted);font-family:var(--font);font-size:var(--fs-sm);' +
    'padding:var(--sp-40) 0;text-align:center;letter-spacing:var(--ls-wide)">' + text + "</div>";
}

function updateInboxBadge(n) {
  const el = document.getElementById("inbox-count");
  if (el) el.textContent = n > 0 ? String(n) : "";
}

async function refreshInbox() {
  const listEl = document.getElementById("inbox-list");
  if (!listEl) return;
  let items = [];
  try {
    const resp = await fetch(`${API_BASE}/inbox`);
    const data = await resp.json();
    items = data.items || [];
  } catch (e) {
    listEl.innerHTML = inboxMsg("FEHLER: " + e);
    return;
  }
  updateInboxBadge(items.length);
  if (!items.length) {
    listEl.innerHTML = inboxMsg("KEINE OFFENEN ENTSCHEIDUNGEN");
    return;
  }
  listEl.innerHTML = "";
  items.forEach((it) => listEl.appendChild(renderInboxItem(it)));
}

function renderInboxItem(item) {
  const card = document.createElement("div");
  card.style.cssText =
    "border:1px solid var(--bd);border-radius:8px;padding:var(--sp-16,16px);" +
    "margin-bottom:var(--sp-12,12px);background:var(--bg-elev,#161616)";

  const title = document.createElement("div");
  title.style.cssText =
    "font-family:var(--font);font-weight:600;letter-spacing:var(--ls-wide);" +
    "color:var(--tx);margin-bottom:var(--sp-8,8px)";
  title.textContent = (item.title || "PIPELINE").toUpperCase();
  card.appendChild(title);

  if (item.prompt) {
    const prompt = document.createElement("div");
    prompt.style.cssText =
      "font-family:var(--font);font-size:var(--fs-sm);color:var(--tx);margin-bottom:var(--sp-8,8px)";
    prompt.textContent = item.prompt;
    card.appendChild(prompt);
  }

  if (item.subject) {
    const subj = document.createElement("pre");
    subj.style.cssText =
      "font-family:var(--font-mono,monospace);font-size:11px;color:var(--tx-muted);" +
      "background:var(--bg,#0e0e0e);border-radius:6px;padding:var(--sp-8,8px);" +
      "white-space:pre-wrap;margin:0 0 var(--sp-12,12px);overflow-x:auto";
    subj.textContent =
      typeof item.subject === "string" ? item.subject : JSON.stringify(item.subject, null, 2);
    card.appendChild(subj);
  }

  card.appendChild(renderInboxActions(item));
  return card;
}

// A response schema that is a single boolean property is the common approve
// pattern — render it as Approve/Reject instead of a checkbox + submit.
function singleBooleanKey(schema) {
  if (!schema || !schema.properties) return null;
  const keys = Object.keys(schema.properties);
  if (keys.length === 1 && schema.properties[keys[0]].type === "boolean") return keys[0];
  return null;
}

function renderInboxActions(item) {
  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex;gap:var(--sp-8,8px);flex-wrap:wrap;align-items:flex-end";

  const boolKey = item.gate_type === "input" ? singleBooleanKey(item.response_schema) : null;

  if (item.gate_type === "approval" || boolKey) {
    wrap.appendChild(
      mkBtn("FREIGEBEN", "primary", () =>
        resolveInbox(item.id, boolKey ? { response: { [boolKey]: true } } : { approve: true })
      )
    );
    wrap.appendChild(
      mkBtn("ABLEHNEN", "ghost", () =>
        resolveInbox(item.id, boolKey ? { response: { [boolKey]: false } } : { approve: false })
      )
    );
  } else {
    const form = buildSchemaForm(item.response_schema);
    wrap.appendChild(form.element);
    wrap.appendChild(mkBtn("ABSCHICKEN", "primary", () => resolveInbox(item.id, { response: form.collect() })));
  }

  wrap.appendChild(mkBtn("ABBRECHEN", "ghost", () => resolveInbox(item.id, { cancel: true })));
  return wrap;
}

function mkBtn(label, variant, onClick) {
  const b = document.createElement("button");
  b.textContent = label;
  const base =
    "font-family:var(--font);font-size:var(--fs-sm);letter-spacing:var(--ls-wide);" +
    "padding:8px 16px;border-radius:6px;cursor:pointer;border:1px solid var(--bd);";
  b.style.cssText =
    base +
    (variant === "primary"
      ? "background:var(--ac,#4a9eff);color:#000;border-color:var(--ac,#4a9eff)"
      : "background:transparent;color:var(--tx-muted)");
  b.addEventListener("click", onClick);
  return b;
}

// Generic field renderer for non-boolean input schemas: boolean -> checkbox,
// enum -> select, number -> number input, else text. collect() coerces by type.
function buildSchemaForm(schema) {
  const el = document.createElement("div");
  el.style.cssText = "display:flex;flex-direction:column;gap:var(--sp-8,8px);width:100%;margin-bottom:var(--sp-8,8px)";
  const fields = {};
  const props = (schema && schema.properties) || {};
  Object.keys(props).forEach((key) => {
    const p = props[key];
    const row = document.createElement("label");
    row.style.cssText = "display:flex;flex-direction:column;gap:4px;font-family:var(--font);font-size:11px;color:var(--tx-muted)";
    row.appendChild(document.createTextNode(key));
    let input;
    if (p.type === "boolean") {
      input = document.createElement("input");
      input.type = "checkbox";
    } else if (p.enum) {
      input = document.createElement("select");
      p.enum.forEach((v) => {
        const o = document.createElement("option");
        o.value = v;
        o.textContent = v;
        input.appendChild(o);
      });
    } else if (p.type === "number" || p.type === "integer") {
      input = document.createElement("input");
      input.type = "number";
    } else {
      input = document.createElement("input");
      input.type = "text";
    }
    input.style.cssText = "background:var(--bg,#0e0e0e);border:1px solid var(--bd);border-radius:6px;padding:6px;color:var(--tx);font-family:var(--font)";
    row.appendChild(input);
    el.appendChild(row);
    fields[key] = { input, type: p.type };
  });
  return {
    element: el,
    collect() {
      const out = {};
      Object.keys(fields).forEach((k) => {
        const f = fields[k];
        if (f.type === "boolean") out[k] = f.input.checked;
        else if (f.type === "number" || f.type === "integer")
          out[k] = f.input.value === "" ? null : Number(f.input.value);
        else out[k] = f.input.value;
      });
      return out;
    },
  };
}

async function resolveInbox(id, body) {
  try {
    const resp = await fetch(`${API_BASE}/inbox/${id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    const res = data.result || {};
    if (res.ok === false && res.error) {
      alert("Pipeline-Fehler: " + (res.error.message || JSON.stringify(res.error)));
    }
  } catch (e) {
    alert("Resolve fehlgeschlagen: " + e);
  }
  await refreshInbox();
}

async function runInboxDemo() {
  try {
    await fetch(`${API_BASE}/pipeline/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pipeline_path: INBOX_DEMO_PIPELINE, title: "Demo HITL" }),
    });
  } catch (e) {
    alert("Demo-Run fehlgeschlagen: " + e);
  }
  await refreshInbox();
}
