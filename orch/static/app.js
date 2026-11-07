"use strict";
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const TABS = ["Board", "Flow", "Planner", "Agents", "AIs", "Settings"];
const COLS = [["backlog", "Backlog"], ["doing", "In progress"], ["review", "Review"], ["blocked", "Needs you"], ["done", "Done"]];
const $ = id => document.getElementById(id);
let tab = "Board", open = null, plannerId = null, flowCard = null, picked = {}, dragging = null, last = null, busy = false;

// Every piece of text from the server is added as a text node, never parsed as markup.
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e[k] = v;
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
}
async function api(path, body) {
  const r = await fetch(path, {method: body === undefined ? "GET" : "POST", headers: {"X-Token": TOKEN, "Content-Type": "application/json"},
                               body: body === undefined ? undefined : JSON.stringify(body)});
  const j = await r.json().catch(() => ({error: "bad reply"}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 3400);
}
const fail = e => toast(e.message || String(e));
const act = (path, body, after) => api(path, body).then(r => { if (r.msg) toast(r.msg); (after || refresh)(r); }, fail);
const fmt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n);
const eta = s => { s = Math.max(0, Math.round(s)); const d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? d + "d " + hh + "h" : hh ? hh + "h " + m + "m" : m + "m"; };
const bar = (f, cls) => h("div", {class: "bar " + (cls || "")}, h("i", {style: "width:" + Math.round(Math.min(Math.max(f, 0), 1) * 100) + "%"}));
const list = (items, done) => items.length ? h("ul", {}, items.map(i => h("li", {}, (done ? (i.done ? "☑ " : "☐ ") : "") + (done ? i.text : i)))) : h("p", {class: "ev"}, "—");

// ---------------------------------------------------------------- header + tabs
function renderHead(s) {
  $("proj").textContent = s.project + " · " + s.base;
  $("pills").replaceChildren(...s.pills.map(p => h("span", {class: "pill"}, (p.ok ? "● " : "○ ") + p.id)),
    ...(s.parallel > 1 ? [h("span", {class: "pill"}, s.parallel + " cards at once")] : []), ...(s.builders > 1 ? [h("span", {class: "pill"}, s.builders + " builders/card")] : []));
  $("dot").className = "dot" + (s.running ? " on" : "");
  $("runtxt").textContent = s.running ? "running" : (s.run_msg || "idle");
  $("run").disabled = s.running; $("stop").disabled = !s.running;
  const pr = $("problems");
  pr.style.display = s.problems.length ? "block" : "none";
  pr.textContent = s.problems.length ? "Before it can run: " + s.problems.join(" · ") : "";
}
function renderTabs() {
  $("tabs").replaceChildren(...TABS.map((t, i) => h("button", {class: t === tab ? "on" : "", onclick: () => { tab = t; renderTabs(); refresh(); }}, (i + 1) + " " + t)));
}

// ---------------------------------------------------------------- card detail (drawer on the board, inline in the Planner tab)
async function detail(id) {
  const c = await api("/api/card/" + encodeURIComponent(id));
  const kids = [h("h3", {}, c.title), h("div", {class: "ev"}, c.id + " · " + c.state + " · " + c.area + (c.phase ? " · " + c.phase : "")),
    h("h4", {}, "Goal"), h("p", {}, c.goal || "—"), h("h4", {}, "Acceptance criteria"), list(c.criteria, true)];
  if (c.moves.length) kids.push(h("div", {class: "row"}, h("span", {class: "ev"}, "Move to:"),
    c.moves.map(to => h("button", {onclick: () => act("/api/move", {id: c.id, to}, r => { if (r.unanswered) toast("Moved to the backlog, but its questions are still unanswered"); closeDrawer(); refresh(); })},
                         to === "blocked" ? "Needs you (hold)" : to))));
  if (c.questions.length) {
    kids.push(h("h4", {}, "The planner needs you"));
    c.questions.forEach((q, i) => {
      const ta = h("textarea", {placeholder: "or type your own answer", value: picked[c.id + i] || "", oninput: ev => { picked[c.id + i] = ev.target.value; }});
      kids.push(h("div", {class: "q"}, h("div", {}, (i + 1) + ". " + q.text),
        q.options.map(o => h("button", {class: "opt" + (picked[c.id + i] === o ? " sel" : ""), onclick: () => { picked[c.id + i] = o; reopen(); }}, o)), ta));
    });
    kids.push(h("div", {class: "row"}, h("button", {onclick: () => act("/api/suggest", {id: c.id}, reopen)}, "Suggest answers"),
      h("button", {class: "primary", onclick: () => act("/api/answer", {id: c.id, answers: c.questions.map((_, i) => picked[c.id + i] || ""), run: true},
        () => { picked = {}; toast("Answered: back in the queue"); closeDrawer(); refresh(); })}, "Send answers & run")));
  }
  kids.push(h("h4", {}, "Plan"), c.plan ? h("pre", {}, c.plan) : h("p", {class: "ev"}, "not planned yet"), h("h4", {}, "Tasks"), list(c.tasks, true));
  if (c.tasks.length) kids.push(bar(c.done / c.tasks.length));
  if (c.out_of_scope) kids.push(h("h4", {}, "Out of scope"), h("pre", {}, c.out_of_scope));
  if (c.answers) kids.push(h("h4", {}, "Your answers"), h("pre", {}, c.answers));
  kids.push(h("h4", {}, "What happened"), c.events.length ? h("div", {}, c.events.map(e => h("div", {class: "ev"}, e.ts.slice(11) + "  " + e.agent + "  " + (e.result || e.kind)))) : h("p", {class: "ev"}, "nothing yet"),
    h("h4", {}, "Card log"), h("pre", {class: "log"}, c.log.join("\n") || "—"));
  return h("div", {class: "detail"}, kids);
}
async function reopen() { if (open) await showDrawer(open); else if (tab === "Planner") refresh(); }
async function showDrawer(id) {
  const d = $("drawer");
  if (d.querySelector("textarea:focus")) return;                    // never wipe what is being typed
  d.replaceChildren(h("button", {onclick: closeDrawer}, "Close"), await detail(id));
  d.classList.add("open");
}
function openCard(id) { if (open !== id) picked = {}; open = id; showDrawer(id).catch(fail); }
function closeDrawer() { open = null; $("drawer").classList.remove("open"); }

// ---------------------------------------------------------------- Board with drag and drop
function cardEl(c) {
  const meta = [h("span", {class: "chip"}, c.area)];
  if (c.phase) meta.push(h("span", {class: "chip run"}, "● " + c.phase));
  if (c.questions) meta.push(h("span", {class: "chip q"}, c.questions + (c.questions === 1 ? " question" : " questions")));
  if (+c.attempts > 0) meta.push(h("span", {class: "chip"}, "try " + c.attempts));
  if (c.depends) meta.push(h("span", {class: "chip"}, "after " + c.depends));
  const col = c.col, canDrag = c.moves.length > 0 || col === "backlog";
  const el = h("div", {class: "card" + (canDrag ? "" : " locked"), draggable: canDrag, onclick: () => openCard(c.id)}, h("div", {class: "t"}, c.title), h("div", {class: "m"}, meta));
  if (c.tasks) el.append(bar(c.done / c.tasks));
  el.dataset.id = c.id;
  el.addEventListener("dragstart", ev => {
    dragging = {id: c.id, from: col, moves: c.moves}; ev.dataTransfer.setData("text/plain", c.id); ev.dataTransfer.effectAllowed = "move";
    setTimeout(() => { el.classList.add("dragging"); document.querySelectorAll(".col").forEach(x => x.classList.add(dropOk(x.dataset.col) ? "drop-ok" : "drop-no")); }, 0);
  });
  el.addEventListener("dragend", () => { dragging = null; document.querySelectorAll(".col,.card").forEach(x => x.classList.remove("drop-ok", "drop-no", "over", "dragging", "ins")); });
  return el;
}
const dropOk = to => dragging && (dragging.moves.includes(to) || (to === "backlog" && dragging.from === "backlog"));
function dropIndex(colEl, y) {
  const cards = [...colEl.querySelectorAll(".card:not(.dragging)")];
  const i = cards.findIndex(x => { const r = x.getBoundingClientRect(); return y < r.top + r.height / 2; });
  return {cards, i: i < 0 ? cards.length : i};
}
function colEl(k, label, cards) {
  const el = h("section", {class: "col"}, h("h2", {}, label, h("span", {}, cards.length)),
    cards.length ? cards.map(c => cardEl({...c, col: k})) : h("div", {class: "empty"}, k === "backlog" ? "Nothing queued: add a request, or drop a card here" : "—"));
  el.dataset.col = k;
  el.addEventListener("dragover", ev => {
    if (!dropOk(k)) return;
    ev.preventDefault(); el.classList.add("over");
    if (k === "backlog") { const {cards: cs, i} = dropIndex(el, ev.clientY); cs.forEach(x => x.classList.remove("ins")); if (cs[i]) cs[i].classList.add("ins"); }
  });
  el.addEventListener("dragleave", ev => { if (!el.contains(ev.relatedTarget)) el.classList.remove("over"); });
  el.addEventListener("drop", ev => {
    ev.preventDefault();
    const d = dragging; if (!d || !dropOk(k)) return;
    if (k === d.from) {                                              // reorder inside the backlog (priority)
      const {cards: cs, i} = dropIndex(el, ev.clientY);
      const ids = cs.map(x => x.dataset.id); ids.splice(i, 0, d.id);
      act("/api/reorder", {ids}, () => { toast("Priority updated"); refresh(true); });
    } else act("/api/move", {id: d.id, to: k}, r => { if (r.unanswered) toast("Moved to the backlog, but its questions are still unanswered"); refresh(true); });
  });
  return el;
}
function renderBoard(s) {
  return h("div", {class: "grid board"}, COLS.filter(([k]) => k !== "review" || s.columns.review.length).map(([k, label]) => colEl(k, label, s.columns[k])));
}

// ---------------------------------------------------------------- Flow
async function renderFlow() {
  const f = await api("/api/flow" + (flowCard ? "?card=" + encodeURIComponent(flowCard) : ""));
  const sel = h("select", {onchange: ev => { flowCard = ev.target.value; refresh(); }}, f.cards.map(c => h("option", {value: c, selected: c === f.card}, c)));
  const kids = [h("div", {class: "row"}, h("h2", {class: "t"}, "Flow of"), f.cards.length ? sel : h("span", {class: "ev"}, "no card yet"), f.attempts ? h("span", {class: "chip"}, "try " + f.attempts) : null),
    f.title ? h("h3", {style: "margin:4px 0"}, f.title) : null, h("div", {class: "ev"}, "▸ " + f.now),
    h("div", {class: "stages"}, f.stages.map(s => h("div", {class: "stage " + s.status}, (s.status === "ok" ? "✓ " : s.status === "fail" ? "× " : "") + s.name)))];
  kids.push(h("h2", {class: "t"}, "Independent reviewers"), h("div", {class: "stages"}, f.reviewers.map(r =>
    h("div", {class: "stage " + r.status}, r.name + " " + (r.verdict || (r.status === "running" ? "…" : "·"))))));
  kids.push(h("h2", {class: "t"}, "What happened"), f.events.length ? h("div", {class: "box"}, f.events.slice().reverse().map(e =>
    h("div", {class: "ev"}, e.ts.slice(11, 16) + "  " + e.agent.padEnd(10) + "  " + (e.result || e.kind) + (e.secs >= 1 ? "  (" + Math.round(e.secs) + "s)" : "")))) : h("div", {class: "ev"}, "nothing yet"));
  return h("div", {}, kids);
}

// ---------------------------------------------------------------- Planner
async function renderPlanner(s) {
  const all = COLS.flatMap(([k, label]) => s.columns[k].map(c => ({...c, col: k, label})));
  if (!plannerId || !all.some(c => c.id === plannerId)) plannerId = (all.find(c => c.col === "blocked") || all[0] || {}).id || null;
  const left = h("div", {class: "box list"}, COLS.map(([k, label]) => s.columns[k].length ? h("div", {}, h("h4", {}, label + " · " + s.columns[k].length),
    s.columns[k].map(c => h("div", {class: "item" + (c.id === plannerId ? " on" : ""), onclick: () => { if (plannerId !== c.id) picked = {}; plannerId = c.id; refresh(); }},
      c.title, c.questions ? h("span", {class: "chip q", style: "margin-left:6px"}, c.questions + "?") : null))) : null));
  const right = h("div", {class: "box"}, plannerId ? await detail(plannerId) : h("div", {class: "ev"}, "No cards yet: add a request."));
  return h("div", {class: "grid two"}, left, right);
}

// ---------------------------------------------------------------- Agents
async function renderAgents() {
  const a = await api("/api/agents");
  return h("div", {class: "grid three"}, a.agents.map(x => h("div", {class: "box agent"}, h("h2", {class: "t"}, x.name, h("span", {class: x.live ? "chip run" : "chip"}, x.live ? "● live" : "idle")),
    h("pre", {class: "log", id: "log-" + x.name}, x.lines.join("\n") || "—"))));
}

// ---------------------------------------------------------------- AIs: who is on, who does what, usage
function usageTable(run, all, ai) {
  const models = Object.keys(all[ai] || {});
  if (!models.length) return h("div", {class: "ev"}, "no calls yet");
  return h("table", {class: "tbl"}, h("tr", {}, ["model", "run calls", "run tokens", "all calls", "all tokens"].map(t => h("th", {}, t))),
    models.map(m => { const r = (run[ai] || {})[m] || {calls: 0, in: 0, out: 0}, a = all[ai][m]; return h("tr", {}, [m, r.calls, fmt(r.in + r.out), a.calls, fmt(a.in + a.out)].map(v => h("td", {}, v))); }));
}
async function renderAIs() {
  const a = await api("/api/ais"), now = Date.now() / 1000;
  const left = [h("div", {class: "row"}, h("h2", {class: "t", style: "margin:0"}, "Use these AIs"),
    h("button", {disabled: a.job.detecting, onclick: () => act("/api/ais/detect", {})}, a.job.detecting ? "Detecting…" : "Detect again"))];
  a.ais.forEach(ai => {
    left.push(h("div", {class: "box", style: "margin-top:10px"}, h("div", {}, h("b", {}, ai.name), " ", h("span", {class: "chip " + (ai.logged_in ? "ok" : "q")}, ai.logged_in ? "logged in" : ai.installed ? "not logged in" : "not installed")),
      ai.models.map(m => h("label", {class: "chk"}, h("input", {type: "checkbox", checked: m.on, onchange: () => act("/api/ais/toggle", {key: m.key})}), m.model,
        m.used_by.length ? h("span", {class: "chip run"}, m.used_by.join(", ")) : null))));
  });
  const roles = h("div", {class: "box"}, h("h2", {class: "t"}, "Who does what"), h("table", {class: "tbl"},
    a.slots.map(s => h("tr", {}, h("td", {}, s.slot), h("td", {}, h("select", {onchange: ev => act("/api/ais/assign", {slot: s.slot, key: ev.target.value})},
      (s.options.includes(s.key) ? s.options : [s.key, ...s.options]).map(o => h("option", {value: o, selected: o === s.key}, o))), s.ok ? null : h("span", {class: "chip fail"}, "not checked above"))))),
    a.same_reviewers ? h("div", {class: "chip q", style: "margin-top:8px"}, "qa and cross use the same model: cross-review is weaker") : null);
  const w = (a.limits.windows || {}), upd = a.limits.updated;
  const win = (label, x) => x && x.utilization != null && !(x.resetsAt && x.resetsAt < now) ? h("div", {style: "margin:8px 0"}, h("div", {class: "row", style: "margin:0"}, label, h("b", {}, Math.round(x.utilization * 100) + "%"),
    x.resetsAt ? h("span", {class: "ev"}, "resets in " + eta(x.resetsAt - now)) : null), bar(x.utilization, x.utilization >= .85 ? "bad" : x.utilization >= .6 ? "warn" : "")) : h("div", {class: "ev"}, label + ": unknown");
  const use = h("div", {class: "box"}, h("h2", {class: "t"}, "Usage · live"), h("div", {class: "row", style: "margin:0"}, h("b", {}, "Claude Code"),
    h("span", {class: "ev"}, "account limits · " + (upd ? "updated " + eta(now - upd) + " ago" : "never read")),
    h("button", {disabled: a.job.probing, onclick: () => act("/api/ais/limits", {})}, a.job.probing ? "Asking…" : "Refresh limits")),
    win("session (5h)", w.five_hour), win("week", w.seven_day),
    a.limits.status && !["allowed", "allowed_warning"].includes(a.limits.status) ? h("div", {class: "chip fail"}, "status: " + a.limits.status) : null,
    usageTable(a.run_use, a.all_use, "claude"),
    ...Object.keys(a.all_use).filter(k => k !== "claude").map(k => h("div", {style: "margin-top:12px"}, h("b", {}, (a.ais.find(x => x.id === k) || {name: k}).name),
      h("span", {class: "ev"}, k === "agy" ? "  quota not shown by agy · tokens only" : "  calls and tokens when the CLI reports them"), usageTable(a.run_use, a.all_use, k))),
    a.job.msg ? h("div", {class: "ev", style: "margin-top:8px"}, a.job.msg) : null);
  return h("div", {class: "grid two", style: "grid-template-columns:minmax(280px,380px) 1fr"}, h("div", {}, left), h("div", {class: "grid"}, roles, use));
}

// ---------------------------------------------------------------- Settings + "Ready to run?"
async function renderSettings() {
  const s = await api("/api/settings");
  const checks = h("div", {class: "box"}, h("h2", {class: "t"}, "Ready to run? · " + s.summary), s.checks.map(c => h("div", {class: "ck " + c.status},
    h("b", {}, c.status === "ok" ? "OK" : c.status === "warn" ? "REVIEW" : "FIX"), h("div", {}, c.title, c.hint ? h("div", {class: "ev"}, c.hint) : null))));
  const rows = s.settings.map(x => {
    let input;
    const save = v => act("/api/settings/set", {key: x.key, value: v});
    if (x.kind === "bool") input = h("input", {type: "checkbox", checked: x.value, onchange: ev => save(ev.target.checked)});
    else if (x.kind === "text") {
      const t = h("input", {type: "text", value: x.value, maxLength: 300});
      input = h("div", {class: "row", style: "margin:0"}, t, h("button", {onclick: () => save(t.value)}, "Save & approve"));
    } else input = h("select", {style: "max-width:220px", onchange: ev => save(x.kind === "choice" ? Number(ev.target.value) : ev.target.value)},
      x.options.map(o => h("option", {value: o, selected: o === x.value}, o + (x.unit || ""))));
    return h("div", {class: "set"}, h("div", {class: "row", style: "margin:0;justify-content:space-between"}, h("b", {}, x.label), input), h("div", {class: "ev"}, x.help));
  });
  return h("div", {class: "grid two", style: "grid-template-columns:minmax(300px,1fr) minmax(300px,1fr)"}, checks, h("div", {class: "box"}, h("h2", {class: "t"}, "Settings"), rows));
}

// ---------------------------------------------------------------- refresh loop
async function refresh(force) {
  if (dragging || busy) return;
  busy = true;
  const t = tab;                                                   // the tab this refresh is for: the user may switch while it waits for the server
  try {
    const s = await api("/api/state"); last = s; renderHead(s);
    if (tab === "Settings" && !force && document.activeElement && ["INPUT", "SELECT"].includes(document.activeElement.tagName) && $("view").contains(document.activeElement)) return;
    if (tab === "Planner" && document.activeElement && document.activeElement.tagName === "TEXTAREA") return;
    const body = tab === "Board" ? renderBoard(s) : tab === "Flow" ? await renderFlow() : tab === "Planner" ? await renderPlanner(s)
      : tab === "Agents" ? await renderAgents() : tab === "AIs" ? await renderAIs() : await renderSettings();
    if (t !== tab) return;
    const keep = tab === "Agents" ? [...document.querySelectorAll("pre.log")].map(p => [p.id, p.scrollTop, p.scrollTop + p.clientHeight >= p.scrollHeight - 4]) : [];
    $("view").replaceChildren(body);
    keep.forEach(([id, top, atEnd]) => { const p = $(id); if (p) p.scrollTop = atEnd ? p.scrollHeight : top; });
    if (open) await showDrawer(open);
  } catch (e) { $("runtxt").textContent = "offline"; } finally { busy = false; if (t !== tab) refresh(); }
}

const nb = $("newbox");
$("newbtn").onclick = () => { nb.showModal(); $("ntext").focus(); };
$("ncancel").onclick = () => nb.close();
$("nsend").onclick = async () => {
  const btn = $("nsend"); btn.disabled = true; btn.textContent = "Understanding…";
  try {
    const r = await api("/api/new", {text: $("ntext").value, area: $("narea").value, ai: $("nai").checked, run: $("nrun").checked});
    nb.close(); $("ntext").value = "";
    toast("Created “" + r.draft.title + "” (" + r.draft.area + ", " + r.draft.source + ")" + (r.started ? " · working on it" : ""));
    refresh(true);
  } catch (e) { fail(e); } finally { btn.disabled = false; btn.textContent = "Create"; }
};
$("run").onclick = () => act("/api/run", {});
$("stop").onclick = () => act("/api/stop", {});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeDrawer();
  else if (/^[1-6]$/.test(e.key) && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) && !nb.open) { tab = TABS[+e.key - 1]; renderTabs(); refresh(); }
});
renderTabs(); refresh(); setInterval(refresh, 2000);
