"use strict";
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const TABS = ["Board", "Flow", "Planner", "Agents", "AIs", "Settings"];
const TAB_HELP = {Board: "Every card by state. Drag to hold or re-queue; reorder the backlog to set priority", Flow: "Where one card is in the pipeline, step by step",
  Planner: "Read a card's goal, plan and tasks, and answer the planner's questions", Agents: "Live output of each AI", AIs: "Which AIs are on, who does what, usage and limits",
  Settings: "Is the project ready to run, and its options"};
const STAGE_HELP = {SPLIT: "A card that is too big is broken into smaller cards that run next.", PLAN: "An AI reads the card and writes a plan and a task list. If something is vague it asks you instead of guessing.",
  BUILD: "The builder AI writes the code for the tasks, inside its own branch.", CHECKS: "Rules first (protected files, diff size, no deleted tests, no secrets), then your CI: lint, tests, build.",
  REVIEW: "Independent reviewers (they did not write the code) check the change against the acceptance criteria.", MERGE: "Approved work is committed and merged into the base branch. Nothing is ever deployed."};
let AREAS = [["", "All"], ["backend", "Backend"], ["frontend", "Frontend"], ["both", "Both"], ["docs", "Docs"]];   // replaced by the project's areas
const STATES_ALL = ["backlog", "doing", "review", "blocked", "done"];
const COLS = [["backlog", "Backlog"], ["doing", "In progress"], ["review", "Review"], ["blocked", "Needs you"], ["done", "Done"]];
const $ = id => document.getElementById(id);
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
const LINK = new URLSearchParams(location.search);              // deep links: ?tab=Flow  ?open=<card id>  ?card=<card id for Flow>  ?new=1&text=...
let filt = {q: "", area: ""}, S = null;
let tab = ["Board", "Flow", "Planner", "Agents", "AIs", "Settings"].includes(LINK.get("tab")) ? LINK.get("tab") : "Board", shown = null, open = null, plannerId = null, flowCard = LINK.get("card"), picked = {}, dragging = null, busy = false, again = false, dropped = false;

// Every piece of text from the server is added as a text node, never parsed as markup.
// Handlers are properties (onclick = ...) so morph() can copy the newest closure onto an element that stays in the page.
// Handlers go through on(): DOM event properties live on the prototype, so morph() could not see them to copy the newest closure.
const on = (el, k, fn) => { (el._on = el._on || {})[k] = fn; el[k] = fn; return el; };
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") e.className = v; else if (k === "key") e.dataset.k = v;
    else if (k === "role") e.setAttribute("role", v); else if (k.startsWith("aria")) e.setAttribute("aria-" + k.slice(4).toLowerCase(), v);
    else if (k.startsWith("on")) on(e, k, v); else e[k] = v;
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) && e.type !== "checkbox") e._srv = e.value;   // what the server last said: morph() leaves the user's edits alone until it changes
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
const fail = e => { toast(e.message || String(e)); refresh(true); };
const act = (path, body, after) => api(path, body).then(r => { if (r.msg) toast(r.msg); (after || (() => refresh(true)))(r); }, fail);
const fmt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(Math.round(n));
const eta = s => { s = Math.max(0, Math.round(s)); const d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? d + "d " + hh + "h" : hh ? hh + "h " + m + "m" : m + "m"; };
const bar = (f, cls) => h("div", {class: "bar " + (cls || ""), role: "progressbar", ariaValueNow: String(Math.round(Math.min(Math.max(f, 0), 1) * 100))},
  h("i", {style: "transform:scaleX(" + Math.min(Math.max(f, 0), 1).toFixed(3) + ")"}));
const level = f => f >= .85 ? "bad" : f >= .6 ? "warn" : "";
const list = (items, done) => items.length ? h("ul", {class: done ? "" : "plain"}, items.map(i => h("li", {class: done && i.done ? "done" : ""}, done ? i.text : i))) : h("p", {class: "ev"}, "None yet");

const num = id => (String(id).match(/^\d+/) || [""])[0];
const match = c => (!filt.area || c.area === filt.area) && (!filt.q || (c.title + " " + c.id).toLowerCase().includes(filt.q));
const filtering = () => !!(filt.q || filt.area);

// ---------------------------------------------------------------- smooth updates
// morph(): make the page look like a freshly built tree by patching it in place. Elements that stay keep their scroll, focus,
// text selection and CSS transitions (progress bars glide); elements that move or appear are animated (FLIP).
const sameKind = (a, b) => a.nodeType === b.nodeType && a.nodeName === b.nodeName;
function patchEl(a, b) {
  for (const at of [...a.attributes]) if (!b.hasAttribute(at.name)) a.removeAttribute(at.name);
  for (const at of b.attributes) if (a.getAttribute(at.name) !== at.value) a.setAttribute(at.name, at.value);
  const bo = b._on || {}, ao = a._on || (a._on = {});
  for (const k of Object.keys(bo)) { a[k] = bo[k]; ao[k] = bo[k]; }
  for (const k of Object.keys(ao)) if (!(k in bo)) { a[k] = null; delete ao[k]; }
  for (const k of ["checked", "disabled", "draggable"]) if (k in b && a[k] !== b[k]) a[k] = b[k];
  morphKids(a, b);
  if (b._srv !== undefined) {                                       // text boxes and dropdowns: the server's value wins only when it changed
    if (a._srv !== b._srv) { if (a !== document.activeElement || a.nodeName === "SELECT") a.value = b._srv; a._srv = b._srv; }
  }
}
function morphKids(a, b) {
  const nk = [...b.childNodes], old = [...a.childNodes], byKey = new Map(), used = new Set();
  for (const o of old) if (o.nodeType === 1 && o.dataset.k) byKey.set(o.dataset.k, o);
  nk.forEach((n, i) => {
    let m = null;
    if (n.nodeType === 1 && n.dataset.k) m = byKey.get(n.dataset.k) || null;
    else { const o = old[i]; if (o && !used.has(o) && sameKind(o, n) && !(o.nodeType === 1 && o.dataset.k)) m = o; }
    if (n.nodeType === 3) { if (m) { if (m.data !== n.data) m.data = n.data; } else m = n; }
    else if (m) patchEl(m, n); else m = n;
    used.add(m);
    const at = a.childNodes[i];
    if (at !== m) a.insertBefore(m, at || null);
  });
  for (const o of [...a.childNodes]) if (!used.has(o)) a.removeChild(o);
}
function morphInto(host, kids, animate) {
  const before = new Map(), flip = animate && !calm;
  if (flip) {                                                       // measure the cards at rest: an animation in flight would give a false position
    host.getAnimations({subtree: true}).forEach(a => a.finish());
    host.querySelectorAll(".card[data-k]").forEach(e => before.set(e.dataset.k, e.getBoundingClientRect()));
  }
  morphKids(host, h("div", {}, kids));
  if (!flip) return;
  host.querySelectorAll(".card[data-k]").forEach(e => {
    const p = before.get(e.dataset.k), n = e.getBoundingClientRect();
    if (p) {
      const dx = p.left - n.left, dy = p.top - n.top;
      if (Math.abs(dx) + Math.abs(dy) > 2) e.animate([{transform: `translate(${dx}px,${dy}px)`}, {transform: "none"}], {duration: 260, easing: "cubic-bezier(.2,.8,.2,1)"});
    } else if (before.size) e.animate([{opacity: 0, transform: "translateY(10px) scale(.97)"}, {opacity: 1, transform: "none"}], {duration: 240, easing: "ease-out"});
  });
}
// Staggered entry when the tab changes: the panels cascade in, one after the other.
function enter(el) {
  if (calm) return;
  const parts = [...(el.children.length > 1 || !el.firstElementChild ? el.children : el.firstElementChild.children)];
  (parts.length > 1 ? parts : [el]).forEach((c, i) => c.animate([{opacity: 0, transform: "translateY(10px)"}, {opacity: 1, transform: "none"}], {duration: 320, delay: Math.min(i, 8) * 45, easing: "cubic-bezier(.2,.8,.2,1)", fill: "backwards"}));
}

// ---------------------------------------------------------------- header + tabs
function go(t) { tab = t; renderTabs(); refresh(true); }
function renderHead(s) {
  morphInto($("proj"), [h("span", {key: "n"}, s.project), h("span", {class: "br", key: "b"}, s.base)]);
  morphInto($("pills"), [...s.pills.map(p => h("span", {class: "pill" + (p.ok ? "" : " off"), key: p.id, title: p.ok ? p.id + " is ready" : p.id + " is not ready (see Settings)"}, p.id)),
    ...(s.parallel > 1 ? [h("span", {class: "pill", key: "par"}, s.parallel + " cards at once")] : []), ...(s.builders > 1 ? [h("span", {class: "pill", key: "bld"}, s.builders + " builders/card")] : [])]);
  $("dot").className = "dot" + (s.running ? " on" : "");
  $("runstate").removeAttribute("title");
  $("runtxt").textContent = s.running ? "running" : (s.run_msg || "idle");
  $("run").disabled = s.running; $("stop").disabled = !s.running;
  const pr = $("problems");
  pr.classList.toggle("show", s.problems.length > 0);
  if (s.problems.length) pr.textContent = "Before it can run: " + s.problems.join("; ");
}
function renderTabs() {
  const need = S ? S.columns.blocked.length : 0;
  morphInto($("tabs"), TABS.map((t, i) => h("button", {key: t, role: "tab", title: TAB_HELP[t], ariaSelected: String(t === tab), class: t === tab ? "on" : "", onclick: () => go(t)},
    h("kbd", {}, String(i + 1)), t, t === "Planner" && need ? h("span", {class: "badge", title: need + " card(s) need your answers"}, String(need)) : null)));
  $("filters").hidden = !["Board", "Planner"].includes(tab);
}

// ---------------------------------------------------------------- card detail (drawer on the board, inline in the Planner tab)
async function detail(id) {
  const c = await api("/api/card/" + encodeURIComponent(id));
  const kids = [h("h3", {}, c.title), h("div", {class: "meta"}, [c.id, c.state, c.area, c.phase].filter(Boolean).map(t => h("span", {}, t))),
    h("h4", {}, "Goal"), h("p", {}, c.goal || "No goal written"), h("h4", {}, "Acceptance criteria"), list(c.criteria, true)];
  if (c.moves.length) kids.push(h("div", {class: "row"}, h("span", {class: "ev"}, "Move to:"),
    c.moves.map(to => h("button", {key: "mv" + to, onclick: () => act("/api/move", {id: c.id, to}, r => { if (r.unanswered) toast("Moved to the backlog, but its questions are still unanswered"); closeDrawer(); refresh(true); })},
                         to === "blocked" ? "Needs you (hold)" : to))));
  if (c.questions.length) {
    kids.push(h("h4", {}, "The planner needs you"));
    c.questions.forEach((q, i) => {
      const ta = h("textarea", {placeholder: "or type your own answer", value: picked[c.id + i] || "", oninput: ev => { picked[c.id + i] = ev.target.value; }});
      kids.push(h("div", {class: "qbox", key: "q" + i}, h("div", {}, (i + 1) + ". " + q.text),
        q.options.map((o, k) => h("button", {key: "o" + k, class: "opt" + (picked[c.id + i] === o ? " sel" : ""), onclick: () => { picked[c.id + i] = o; refresh(true); }}, o)), ta));
    });
    kids.push(h("div", {class: "row"}, h("button", {onclick: () => act("/api/suggest", {id: c.id}, () => refresh(true))}, "Suggest answers"),
      h("button", {class: "primary", onclick: () => act("/api/answer", {id: c.id, answers: c.questions.map((_, i) => picked[c.id + i] || ""), run: true},
        () => { picked = {}; toast("Answered: back in the queue"); closeDrawer(); refresh(true); })}, "Send answers & run")));
  }
  kids.push(h("h4", {}, "Plan"), c.plan ? h("pre", {}, c.plan) : h("p", {class: "ev"}, "not planned yet"), h("h4", {}, "Tasks"), list(c.tasks, true));
  if (c.tasks.length) kids.push(bar(c.done / c.tasks.length));
  if (c.out_of_scope) kids.push(h("h4", {}, "Out of scope"), h("pre", {}, c.out_of_scope));
  if (c.answers) kids.push(h("h4", {}, "Your answers"), h("pre", {}, c.answers));
  kids.push(h("h4", {}, "What happened"), c.events.length ? h("div", {}, c.events.map(e => h("div", {class: "ev"}, e.ts.slice(11) + "  " + e.agent + "  " + (e.result || e.kind)))) : h("p", {class: "ev"}, "nothing yet"),
    h("h4", {}, "Card log"), h("pre", {class: "log"}, c.log.join("\n") || "Empty"));
  return h("div", {class: "detail"}, kids);
}
async function showDrawer(id) {
  const d = $("drawer"), body = await detail(id);
  if (open !== id) return;
  morphInto(d, [h("div", {key: "x", class: "dhead"}, h("span", {class: "mono ev"}, "Card " + (num(id) || id)), h("button", {class: "quiet", onclick: closeDrawer, title: "Esc"}, "Close")), body], false);
  d.classList.add("open");
  $("scrim").classList.add("on");
}
function openCard(id) { if (open !== id) picked = {}; open = id; $("drawer").scrollTop = 0; showDrawer(id).catch(fail); }
function closeDrawer() { open = null; $("drawer").classList.remove("open"); $("scrim").classList.remove("on"); }
$("scrim").onclick = closeDrawer;

// ---------------------------------------------------------------- Board with drag and drop
function cardEl(c) {
  const meta = [h("span", {class: "cid", key: "n"}, "#" + num(c.id)), h("span", {class: "chip", key: "a"}, c.area)];
  if (c.phase) meta.push(h("span", {class: "chip run", key: "p"}, c.phase));
  if (c.questions) meta.push(h("span", {class: "chip q", key: "q"}, c.questions + (c.questions === 1 ? " question" : " questions")));
  if (+c.attempts > 0) meta.push(h("span", {class: "chip", key: "t"}, "try " + c.attempts));
  if (c.depends) meta.push(h("span", {class: "chip", key: "d"}, "after " + c.depends));
  const canDrag = c.moves.length > 0 || c.col === "backlog";
  const el = h("div", {key: c.id, class: "card" + (canDrag ? "" : " locked") + (c.phase ? " live" : "") + (c.questions ? " ask" : ""), draggable: canDrag, onclick: () => openCard(c.id)},
    h("div", {class: "t"}, c.title), h("div", {class: "m"}, meta));
  if (c.tasks) el.append(bar(c.done / c.tasks));
  el.dataset.id = c.id;
  on(el, "ondragstart", ev => {
    const me = ev.currentTarget;                                      // never the captured `el`: after morph() the live element is another one
    dragging = {id: c.id, from: c.col, moves: c.moves}; dropped = false; ev.dataTransfer.setData("text/plain", c.id); ev.dataTransfer.effectAllowed = "move";
    setTimeout(() => { me.classList.add("dragging"); document.querySelectorAll(".col").forEach(x => x.classList.add(dropOk(x.dataset.col) ? "drop-ok" : "drop-no")); }, 0);
  });
  on(el, "ondragend", () => { dragging = null; document.querySelectorAll(".col,.card").forEach(x => x.classList.remove("drop-ok", "drop-no", "over", "dragging", "ins")); if (!dropped) refresh(); });   // after a drop the server answer refreshes
  return el;
}
const dropOk = to => dragging && (dragging.moves.includes(to) || (to === "backlog" && dragging.from === "backlog"));
function dropIndex(colNode, y) {
  const cards = [...colNode.querySelectorAll(".card:not(.dragging)")];
  const i = cards.findIndex(x => { const r = x.getBoundingClientRect(); return y < r.top + r.height / 2; });
  return {cards, i: i < 0 ? cards.length : i};
}
function colEl(k, label, all) {
  const cards = all.filter(match);
  const el = h("section", {key: k, class: "col" + (k === "blocked" && all.length ? " need" : ""), ariaLabel: label}, h("h2", {key: "h"}, label, h("span", {}, filtering() ? cards.length + " of " + all.length : all.length)),
    cards.length ? cards.map(c => cardEl({...c, col: k})) : filtering() && all.length ? h("div", {key: "empty", class: "empty"}, [h("b", {}, "No match"), all.length + " hidden by the filter"]) : h("div", {key: "empty", class: "empty"}, k === "backlog" ? [h("b", {}, "Nothing queued"), "Use New request, or drop a card here"]
      : k === "blocked" ? [h("b", {}, "Nothing needs you"), "Questions from the planner show up here"] : k === "doing" ? [h("b", {}, "Idle"), "Press Run to work the backlog"] : [h("b", {}, "No finished cards yet")]));
  el.dataset.col = k;
  on(el, "ondragover", ev => {
    if (!dropOk(k)) return;
    const col = ev.currentTarget;
    ev.preventDefault(); col.classList.add("over");
    if (k === "backlog") { const {cards: cs, i} = dropIndex(col, ev.clientY); cs.forEach(x => x.classList.remove("ins")); if (cs[i]) cs[i].classList.add("ins"); }
  });
  on(el, "ondragleave", ev => { if (!ev.currentTarget.contains(ev.relatedTarget)) ev.currentTarget.classList.remove("over"); });
  on(el, "ondrop", ev => {
    ev.preventDefault();
    const col = ev.currentTarget, d = dragging; if (!d || !dropOk(k)) return;
    dropped = true;
    const node = [...document.querySelectorAll(".card")].find(n => n.dataset.id === d.id);
    if (k === d.from) {                                              // reorder inside the backlog (priority)
      const {cards: cs, i} = dropIndex(col, ev.clientY);
      const ids = cs.map(x => x.dataset.id); ids.splice(i, 0, d.id);
      if (node) col.insertBefore(node, cs[i] || null);                // the card lands at once; the server confirms
      act("/api/reorder", {ids}, () => { toast("Priority updated"); refresh(true); });
    } else {
      if (node) { col.querySelector(".empty")?.remove(); col.append(node); }
      act("/api/move", {id: d.id, to: k}, r => { if (r.unanswered) toast("Moved to the backlog, but its questions are still unanswered"); refresh(true); });
    }
  });
  return el;
}
// The board in numbers: what a scrum master asks first (how far along, what is in flight, what is stuck on us).
function summary(s) {
  const c = s.columns, n = k => c[k].length, total = STATES_ALL.reduce((a, k) => a + n(k), 0);
  const wip = [...c.doing, ...c.review], tasks = wip.reduce((a, x) => a + x.tasks, 0), tdone = wip.reduce((a, x) => a + x.done, 0);
  const qs = c.blocked.reduce((a, x) => a + x.questions, 0), first = c.blocked[0];
  const stat = (k, cls, label, value, sub, extra) => h("div", {class: "stat " + cls, key: k}, h("span", {class: "k"}, label), h("span", {class: "v"}, value), sub ? h("span", {class: "s"}, sub) : null, extra);
  return h("div", {class: "summary", key: "sum", role: "group", ariaLabel: "Board summary"},
    stat("done", "", "Done", total ? Math.round(n("done") / total * 100) + "%" : "0%", n("done") + " of " + total + " cards", total ? bar(n("done") / total) : null),
    stat("wip", "", "In progress", String(wip.length), tasks ? tdone + " of " + tasks + " tasks done" : s.running ? "waiting for the next card" : "pipeline idle", tasks ? bar(tdone / tasks) : null),
    stat("need", n("blocked") ? "need" : "", "Needs you", String(n("blocked")), n("blocked") ? (qs ? qs + (qs === 1 ? " question to answer" : " questions to answer") : "held by you") : "nothing is waiting on you",
      first ? h("button", {onclick: () => openCard(first.id)}, qs ? "Answer the first" : "Open the first") : null),
    stat("queue", "", "Queued", String(n("backlog")), n("backlog") ? "next: " + c.backlog[0].title : "add a request to start"));
}
function renderBoard(s) {
  return h("div", {}, summary(s), h("div", {class: "grid board", key: "cols"}, COLS.filter(([k]) => k !== "review" || s.columns.review.length).map(([k, label]) => colEl(k, label, s.columns[k]))));
}

// ---------------------------------------------------------------- Flow
async function renderFlow() {
  const f = await api("/api/flow" + (flowCard ? "?card=" + encodeURIComponent(flowCard) : ""));
  const sel = h("select", {onchange: ev => { flowCard = ev.target.value; refresh(true); }}, f.cards.map(c => h("option", {value: c, selected: c === f.card, key: c}, c)));
  const kids = [h("div", {class: "row", key: "top"}, h("h2", {class: "t"}, "Flow of"), f.cards.length ? sel : h("span", {class: "ev"}, "no card yet"), f.attempts ? h("span", {class: "chip"}, "try " + f.attempts) : null),
    h("h3", {style: "margin:4px 0", key: "title"}, f.title || ""), h("div", {class: "ev", key: "now"}, f.now),
    h("div", {class: "stages", key: "stages"}, f.stages.map(s => h("div", {class: "stage " + s.status, key: s.name, title: STAGE_HELP[s.name] || ""}, s.name))),
    h("p", {class: "ev", key: "hint"}, "Hover a step to see what it does, or press ? for the whole flow.")];
  kids.push(h("h2", {class: "t", key: "rv"}, "Independent reviewers"), h("div", {class: "stages", key: "revs"}, f.reviewers.map(r =>
    h("div", {class: "stage " + r.status, key: r.name}, r.name + " " + (r.verdict ? r.verdict.toLowerCase() : r.status === "running" ? "reviewing" : "waiting")))));
  const tone = r => /fail|reject|violation|blocked|invalid/i.test(r) ? "fail" : /pass|approved|done|planned/i.test(r) ? "ok" : "";
  kids.push(h("h2", {class: "t", key: "wh"}, "What happened"), f.events.length ? h("div", {class: "box scroll", key: "ev"}, h("table", {class: "tbl left"},
    h("tr", {}, ["time", "who", "result", "took"].map(t => h("th", {}, t))),
    f.events.slice().reverse().map((e, i) => { const r = e.result || e.kind; return h("tr", {key: e.ts + e.agent + e.kind + i}, h("td", {}, e.ts.slice(11, 16)), h("td", {}, e.agent), h("td", {class: tone(r)}, r), h("td", {}, e.secs >= 1 ? Math.round(e.secs) + "s" : "")); })))
    : h("div", {class: "ev", key: "ev"}, "nothing yet"));
  return h("div", {}, kids);
}

// ---------------------------------------------------------------- Planner
async function renderPlanner(s) {
  const all = COLS.flatMap(([k, label]) => s.columns[k].map(c => ({...c, col: k, label})));
  if (!plannerId || !all.some(c => c.id === plannerId)) plannerId = (all.find(c => c.col === "blocked") || all[0] || {}).id || null;
  const shown = k => s.columns[k].filter(match);
  const left = h("div", {class: "box list", key: "l"}, COLS.map(([k, label]) => shown(k).length ? h("div", {key: k}, h("h4", {}, label, h("span", {class: "n"}, shown(k).length)),
    shown(k).map(c => h("div", {key: c.id, class: "item" + (c.id === plannerId ? " on" : ""), onclick: () => { if (plannerId !== c.id) picked = {}; plannerId = c.id; refresh(true); }},
      h("span", {class: "cid"}, "#" + num(c.id)), " ", c.title, c.questions ? h("span", {class: "chip q", style: "margin-left:6px"}, c.questions + "?") : null))) : null));
  const right = h("div", {class: "box", key: "r"}, plannerId ? await detail(plannerId) : h("div", {class: "ev"}, "No cards yet: add a request."));
  return h("div", {class: "grid two"}, left, right);
}

// ---------------------------------------------------------------- Agents
async function renderAgents() {
  const a = await api("/api/agents");
  return h("div", {class: "grid three"}, a.agents.map(x => h("div", {class: "box agent", key: x.name}, h("h2", {class: "t"}, x.name, h("span", {class: x.live ? "chip run" : "chip"}, x.live ? "live" : "idle")),
    h("pre", {class: "log", id: "log-" + x.name}, x.lines.join("\n") || "No output yet"))));
}

// ---------------------------------------------------------------- AIs: who is on, who does what, usage, budgets
const PERS = ["5h", "day", "week", "month"];
function cell(w, unit) { if (!w) return "-"; const v = unit === "cost" ? "$" + w.cost.toFixed(2) : fmt(w.in + w.out); return (w.est ? "~" : "") + v; }
function usageTable(a, ai) {
  const models = Object.keys(a.all_use[ai] || {});
  if (!models.length) return h("div", {class: "ev"}, "no calls yet");
  const money = models.some(m => (a.all_use[ai][m].cost || 0) > 0);
  return h("div", {class: "scroll"}, h("table", {class: "tbl"}, h("tr", {}, ["model", "calls", "this run", "5h", "day", "week", "all", ...(money ? ["cost"] : [])].map(t => h("th", {}, t))),
    models.map(m => {
      const all = a.all_use[ai][m], run = (a.run_use[ai] || {})[m], w = ((a.windows[ai] || {})[m]) || {};
      const tok = v => v ? (v.est ? "~" : "") + fmt(v.in + v.out) : "-";
      return h("tr", {key: m}, [m, all.calls, tok(run), tok(w["5h"]), tok(w.day), tok(w.week), tok(all), ...(money ? ["$" + all.cost.toFixed(2)] : [])].map(v => h("td", {}, v)));
    })));
}
function budgetBlock(a, ai) {
  const mine = a.budgets.filter(b => b.key.split("/")[0] === ai);
  const unit = h("select", {}, ["tokens", "calls", "cost"].map(u => h("option", {value: u}, u === "cost" ? "cost (USD)" : u)));
  const lim = h("input", {type: "text", placeholder: "limit", style: "max-width:110px", inputMode: "decimal"});
  const per = h("select", {}, PERS.map(p => h("option", {value: p, selected: p === "day"}, "per " + p)));
  const rows = mine.map(b => h("div", {key: b.key + b.unit, style: "margin:8px 0"}, h("div", {class: "row", style: "margin:0"}, h("b", {}, b.key), b.unit,
    h("span", {class: "ev"}, (b.unit === "cost" ? "$" + b.used.toFixed(2) + " of $" + b.limit : fmt(b.used) + " of " + fmt(b.limit)) + " per " + b.per + (b.est ? " (estimated)" : "") + (b.used ? ", oldest call leaves in " + eta(b.resets_in) : "")),
    h("button", {title: "remove this limit", onclick: () => act("/api/budget", {key: b.key, unit: b.unit, per: b.per, limit: 0})}, "×")), bar(b.frac, level(b.frac))));
  return h("div", {key: "bud-" + ai}, rows, h("div", {class: "row"}, h("span", {class: "ev"}, "My limit:"), unit, lim, per,
    h("button", {onclick: ev => {                                    // read the fields on the page (the ones built above are replaced on every refresh)
      const row = ev.currentTarget.parentElement, [u, p] = row.querySelectorAll("select"), l = row.querySelector("input");
      act("/api/budget", {key: ai, unit: u.value, per: p.value, limit: l.value}, () => { l.value = ""; refresh(true); });
    }}, "Set")));
}
async function renderAIs() {
  const a = await api("/api/ais"), now = Date.now() / 1000;
  const left = [h("div", {class: "row", key: "hd"}, h("h2", {class: "t", style: "margin:0"}, "Use these AIs"),
    h("button", {disabled: a.job.detecting, onclick: () => act("/api/ais/detect", {})}, a.job.detecting ? "Detecting…" : "Detect again"))];
  a.ais.forEach(ai => {
    left.push(h("div", {class: "box", key: ai.id, style: "margin-top:10px"}, h("div", {}, h("b", {}, ai.name), " ", h("span", {class: "chip " + (ai.logged_in ? "ok" : "q")}, ai.logged_in ? "logged in" : ai.installed ? "not logged in" : "not installed")),
      ai.models.map(m => h("label", {class: "chk", key: m.key}, h("input", {type: "checkbox", checked: m.on, onchange: () => act("/api/ais/toggle", {key: m.key})}), m.model,
        m.used_by.length ? h("span", {class: "chip"}, m.used_by.join(", ")) : null))));
  });
  const roles = h("div", {class: "box", key: "roles"}, h("h2", {class: "t"}, "Who does what"), h("table", {class: "tbl"},
    a.slots.map(s => h("tr", {key: s.slot}, h("td", {}, s.slot), h("td", {}, h("select", {onchange: ev => act("/api/ais/assign", {slot: s.slot, key: ev.target.value})},
      (s.options.includes(s.key) ? s.options : [s.key, ...s.options]).map(o => h("option", {value: o, selected: o === s.key, key: o}, o))), s.ok ? null : h("span", {class: "chip fail"}, "not checked above")),
      h("td", {}, s.takes_effort ? h("select", {ariaLabel: s.slot + " effort", title: "How hard this model thinks (more = slower, better on hard cards)", onchange: ev => act("/api/ais/assign", {slot: s.slot, effort: ev.target.value})},
        ["", ...a.efforts].map(e => h("option", {value: e, selected: e === s.effort, key: "e" + e}, e ? "effort " + e : "default effort"))) : h("span", {class: "ev", title: "This CLI takes no effort setting"}, "n/a"))))),
    a.same_reviewers ? h("div", {class: "chip q", style: "margin-top:8px"}, "qa and cross use the same model: cross-review is weaker") : null);
  const w = (a.limits.windows || {}), upd = a.limits.updated;
  const win = (label, x) => x && x.utilization != null && !(x.resetsAt && x.resetsAt < now) ? h("div", {style: "margin:8px 0", key: label}, h("div", {class: "row", style: "margin:0"}, label, h("b", {}, Math.round(x.utilization * 100) + "%"),
    x.resetsAt ? h("span", {class: "ev"}, "resets in " + eta(x.resetsAt - now)) : null), bar(x.utilization, level(x.utilization))) : h("div", {class: "ev", key: label}, label + ": unknown");
  const others = [...new Set([...Object.keys(a.all_use), ...a.budgets.map(b => b.key.split("/")[0]), ...a.ais.filter(x => x.installed && x.id !== "claude").map(x => x.id)])].filter(k => k !== "claude");
  const nameOf = k => (a.ais.find(x => x.id === k) || {name: k}).name;
  const use = h("div", {class: "box", key: "usage"}, h("h2", {class: "t"}, "Usage"),
    h("div", {class: "row", style: "margin:0"}, h("b", {}, "Claude Code"), h("span", {class: "ev"}, "account limits, " + (upd ? "updated " + eta(now - upd) + " ago" : "never read")),
      h("button", {disabled: a.job.probing, onclick: () => act("/api/ais/limits", {})}, a.job.probing ? "Asking…" : "Refresh limits")),
    win("session (5h)", w.five_hour), win("week", w.seven_day),
    a.limits.status && !["allowed", "allowed_warning"].includes(a.limits.status) ? h("div", {class: "chip fail"}, "status: " + a.limits.status) : null,
    usageTable(a, "claude"), budgetBlock(a, "claude"),
    ...others.map(k => h("div", {key: "ai-" + k, style: "margin-top:16px"}, h("b", {}, nameOf(k)),
      h("span", {class: "ev"}, k === "agy" ? "  Antigravity does not publish its quota: tokens are exact, set your own limit" : "  ~ = estimated (this CLI reports no tokens): set your own limit"), usageTable(a, k), budgetBlock(a, k))),
    a.job.msg ? h("div", {class: "ev", style: "margin-top:8px"}, a.job.msg) : null);
  return h("div", {class: "grid two", style: "grid-template-columns:minmax(280px,380px) 1fr"}, h("div", {}, left), h("div", {class: "grid"}, roles, use));
}

// ---------------------------------------------------------------- Settings + "Ready to run?"
async function renderSettings() {
  const s = await api("/api/settings");
  const checks = h("div", {class: "box", key: "c"}, h("h2", {class: "t"}, "Ready to run?", h("span", {class: "n"}, s.summary)), s.checks.map((c, i) => h("div", {class: "ck " + c.status, key: "ck" + i},
    h("b", {}, c.status === "ok" ? "OK" : c.status === "warn" ? "REVIEW" : "FIX"),
    h("div", {}, c.title, c.hint ? h("div", {class: "ev"}, c.hint) : null,
      c.action === "context" ? h("button", {style: "margin-top:8px", onclick: () => act("/api/context", {})}, "Study the project now") : null))));
  const rows = s.settings.map(x => {
    let input;
    const save = v => act("/api/settings/set", {key: x.key, value: v});
    if (x.kind === "bool") input = h("input", {type: "checkbox", checked: x.value, onchange: ev => save(ev.target.checked)});
    else if (x.kind === "text") {
      const t = h("input", {type: "text", value: x.value, maxLength: 300});
      input = h("div", {class: "row", style: "margin:0"}, t, h("button", {onclick: ev => save(ev.currentTarget.parentElement.querySelector("input").value)}, "Save & approve"));
    } else input = h("select", {style: "max-width:220px", onchange: ev => save(x.kind === "choice" ? Number(ev.target.value) : ev.target.value)},
      x.options.map(o => h("option", {value: o, selected: o === x.value, key: o}, o + (x.unit || ""))));
    return h("div", {class: "set", key: x.key}, h("div", {class: "row", style: "margin:0;justify-content:space-between"}, h("b", {}, x.label), input), h("div", {class: "ev"}, x.help));
  });
  return h("div", {class: "grid two", style: "grid-template-columns:minmax(300px,1fr) minmax(300px,1fr)"}, checks, h("div", {class: "box", key: "s"}, h("h2", {class: "t"}, "Settings"), rows));
}

// ---------------------------------------------------------------- refresh loop
async function refresh() {
  if (dragging) return;
  if (busy) { again = true; return; }                              // asked while one is running: run once more right after, so no change is lost
  busy = true;
  const t = tab;                                                   // the tab this refresh is for: the user may switch while it waits for the server
  try {
    const s = await api("/api/state"); S = s; renderHead(s); renderTabs(); setAreas(s.areas || []);
    const body = t === "Board" ? renderBoard(s) : t === "Flow" ? await renderFlow() : t === "Planner" ? await renderPlanner(s)
      : t === "Agents" ? await renderAgents() : t === "AIs" ? await renderAIs() : await renderSettings();
    if (t !== tab) return;
    const logs = t === "Agents" ? [...document.querySelectorAll("pre.log")].map(p => [p.id, p.scrollTop + p.clientHeight >= p.scrollHeight - 4]) : [];
    const switched = shown !== t;
    if (switched) { $("view").replaceChildren(body); enter(body); } else morphInto($("view"), [body], true);
    shown = t;
    logs.forEach(([id, atEnd]) => { const p = $(id); if (p && atEnd) p.scrollTop = p.scrollHeight; });
    if (open) await showDrawer(open);
  } catch (e) { $("runtxt").textContent = "offline"; $("runstate").title = "The page cannot reach lonerchestrator web: is it still running?"; $("dot").className = "dot"; } finally { busy = false; if (again || t !== tab) { again = false; refresh(); } }
}

const nb = $("newbox");
$("newbtn").onclick = () => { nb.showModal(); $("ntext").focus(); };
$("ncancel").onclick = () => nb.close();
$("nsend").onclick = async () => {
  const btn = $("nsend"); btn.disabled = true; btn.textContent = "Understanding…";
  try {
    const r = await api("/api/new", {text: $("ntext").value, area: $("narea").value, ai: $("nai").checked, run: $("nrun").checked});
    nb.close(); $("ntext").value = "";
    toast("Created “" + r.draft.title + "” (" + r.draft.area + ", " + r.draft.source + ")" + (r.started ? ", working on it" : ""));
    refresh();
  } catch (e) { toast(e.message); } finally { btn.disabled = false; btn.textContent = "Create"; }
};
$("run").onclick = () => act("/api/run", {});
$("stop").onclick = () => act("/api/stop", {});
// Theme: auto follows the system; the choice is remembered in this browser only.
const THEMES = ["auto", "light", "dark"];
function setTheme(t) {
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  $("theme").textContent = t[0].toUpperCase() + t.slice(1); $("theme").title = "Theme: " + t + " (t to switch)";
  try { localStorage.setItem("lc-theme", t); } catch { /* private window: not remembered */ }
}
let saved = "auto"; try { saved = localStorage.getItem("lc-theme") || "auto"; } catch { /* ignore */ }
setTheme(THEMES.includes(saved) ? saved : "auto");
const cycleTheme = () => setTheme(THEMES[(THEMES.indexOf(document.documentElement.dataset.theme || "auto") + 1) % 3]);
$("theme").onclick = cycleTheme;

// Help: the flow in plain words, and the keys.
const hb = $("helpbox");
const steps = rows => h("ol", {class: "steps"}, rows.map(([k, v]) => h("li", {}, h("b", {}, k), h("span", {}, v))));
function showHelp() {
  $("helpbody").replaceChildren(
    h("p", {class: "ev"}, "You write a request in plain words. AIs plan it, build it, check it and review it; it is merged only when every reviewer approves. If anything is unclear, the card lands in Needs you with questions."),
    h("h4", {}, "The steps every card goes through"), steps(Object.entries(STAGE_HELP)),
    h("h4", {}, "Board columns"), steps([["Backlog", "Waiting its turn. Drag cards to set the order."], ["In progress", "An AI is working on it now."], ["Needs you", "Questions for you, or held by you. Answer them in the card."], ["Done", "Approved and merged."]]),
    h("h4", {}, "Keys"), steps([["1 to 6", "switch tab"], ["n", "new request"], ["/", "filter cards"], ["t", "switch theme"], ["?", "this help"], ["Esc", "close a panel"]]));
  hb.showModal();
}
$("helpbtn").onclick = showHelp;
$("hclose").onclick = () => hb.close();

// Filters (Board and Planner): by text and by area.
function renderAreas() {
  $("areas").replaceChildren(...AREAS.map(([v, label]) => h("button", {ariaPressed: String(filt.area === v), onclick: () => { filt.area = v; renderAreas(); refresh(true); }}, label)));
}
// The project's areas (keys of `agents` in its config): the filter and the "Built by" list follow them.
function setAreas(list) {
  if (!list.length || list.join() === setAreas.last) return;
  setAreas.last = list.join();
  AREAS = [["", "All"], ...list.map(a => [a, a[0].toUpperCase() + a.slice(1)])];
  if (filt.area && !list.includes(filt.area)) filt.area = "";
  renderAreas();
  const sel = $("narea"), keep = sel.value;
  sel.replaceChildren(h("option", {value: ""}, "auto (the AI decides)"), ...list.map(a => h("option", {value: a}, a)));
  sel.value = list.includes(keep) ? keep : "";
}
renderAreas();
$("q").oninput = e => { filt.q = e.target.value.trim().toLowerCase(); refresh(true); };

document.addEventListener("keydown", e => {
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) || nb.open || hb.open;
  if (e.key === "Escape") { if (document.activeElement === $("q") && filt.q) { $("q").value = ""; filt.q = ""; refresh(true); } closeDrawer(); }
  else if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  else if (/^[1-6]$/.test(e.key)) go(TABS[+e.key - 1]);
  else if (e.key === "n") { e.preventDefault(); $("newbtn").click(); }
  else if (e.key === "/") { e.preventDefault(); if (!["Board", "Planner"].includes(tab)) go("Board"); $("q").focus(); }
  else if (e.key === "t") cycleTheme();
  else if (e.key === "?") showHelp();
});
$("view").replaceChildren(h("div", {class: "grid board"}, [0, 1, 2, 3].map(i => h("div", {class: "col"}, h("div", {class: "sk", style: "height:14px;width:40%;margin:4px 4px 14px"}),
  h("div", {class: "sk card"}), i < 2 ? h("div", {class: "sk card", style: "margin-top:10px"}) : null))));
renderTabs(); refresh();
if (!LINK.get("still")) setInterval(refresh, 1500);                // ?still=1 freezes the page after the first render (screenshots, demos)
if (LINK.get("open")) setTimeout(() => openCard(LINK.get("open")), 700);
if (LINK.get("new")) { $("ntext").value = LINK.get("text") || ""; nb.showModal(); }
