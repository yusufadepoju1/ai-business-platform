/* Shell, router, shared UI helpers, dashboard / business / analytics / settings pages. */
const PAGES = {};
const NAV = [["dashboard", "Dashboard"], ["conversations", "Conversations"], ["crm", "CRM & leads"], ["customers", "Customers"],
  ["sep", "Assistants"], ["knowledge", "Knowledge base"], ["agents", "AI agents"], ["test", "Agent testing"],
  ["sep", "Connect"], ["automations", "Automations"], ["integrations", "Integrations"],
  ["sep", "Workspace"], ["analytics", "Analytics"], ["business", "Business settings"], ["settings", "User settings"]];
const state = { user: null, charts: [] };
const isAdmin = () => ["owner", "admin"].includes(state.user.role);
const spinner = () => '<div class="spinner" role="status" aria-label="Loading"></div>';
const empty = (t, d) => `<div class="empty"><b>${esc(t)}</b>${esc(d || "")}</div>`;
const badge = (v, map = {}) => { const c = map[v] || ""; return `<span class="badge ${c}">${esc(String(v).replace("_", " "))}</span>`; };
const STATUS_B = { new: "b-blue", contacted: "b-amber", qualified: "b-green", converted: "b-green", lost: "b-red", open: "b-blue", resolved_ai: "b-green", escalated: "b-red", closed: "", ready: "b-green", failed: "b-red", processing: "b-amber", hot: "b-red", warm: "b-amber", cold: "b-blue", pending: "b-amber", done: "b-green", success: "b-green", skipped: "b-amber" };
const sb = (v) => badge(v, STATUS_B);
const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
function table(cols, rows, emptyHtml) {
  if (!rows.length) return emptyHtml;
  return `<div class="tablewrap"><table><thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}
function destroyCharts() { state.charts.forEach(c => c.destroy()); state.charts = []; }
function chart(id, cfg) {
  const el = document.getElementById(id); if (!el || typeof Chart === "undefined") { if (el) el.parentElement.innerHTML = empty("Charts unavailable", "Chart.js could not be loaded."); return; }
  cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } }, cfg.options || {});
  state.charts.push(new Chart(el, cfg));
}
function dialog({ title, body, submit = "Save", onSubmit, wide }) {
  const d = document.getElementById("dlg");
  d.innerHTML = `<h2>${esc(title)}</h2><form id="dform" novalidate>${body}<div class="err" id="derr" role="alert" style="color:var(--coral);margin-bottom:.5rem"></div><div class="row" style="justify-content:flex-end"><button type="button" class="btn ghost" id="dcancel">${onSubmit ? "Cancel" : "Close"}</button>${onSubmit ? `<button class="btn" id="dok">${esc(submit)}</button>` : ""}</div></form>`;
  d.querySelector("#dcancel").onclick = () => d.close();
  const f = d.querySelector("#dform");
  f.onsubmit = async (e) => {
    e.preventDefault(); if (!onSubmit) return; if (!validateForm(f)) return;
    await withBusy(d.querySelector("#dok"), async () => { try { await onSubmit(Object.fromEntries(new FormData(f)), d); } catch (x) { d.querySelector("#derr").textContent = x.message; } });
  };
  d.showModal(); return d;
}
const field = (label, name, o = {}) => `<div class="field"><label for="f_${name}">${esc(label)}</label>${o.type === "textarea" ? `<textarea id="f_${name}" name="${name}" ${o.required ? "required" : ""} maxlength="${o.max || 4000}">${esc(o.value || "")}</textarea>` : o.type === "select" ? `<select id="f_${name}" name="${name}">${o.options.map(v => { const [val, lab] = Array.isArray(v) ? v : [v, v]; return `<option value="${esc(val)}" ${String(o.value) === String(val) ? "selected" : ""}>${esc(lab)}</option>`; }).join("")}</select>` : `<input id="f_${name}" name="${name}" type="${o.type || "text"}" value="${esc(o.value || "")}" ${o.required ? "required" : ""} ${o.min ? `minlength="${o.min}"` : ""} ${o.placeholder ? `placeholder="${esc(o.placeholder)}"` : ""} autocomplete="off">`}${o.hint ? `<span class="hint">${esc(o.hint)}</span>` : ""}</div>`;
const confirmBox = (msg) => window.confirm(msg);
const kpi = (l, v, sub) => `<div class="card kpi"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div>${sub ? `<div class="small muted">${esc(sub)}</div>` : ""}</div>`;
const copyBtn = (text) => `<button class="btn ghost sm" data-copy="${esc(text)}">Copy</button>`;
document.addEventListener("click", (e) => { const b = e.target.closest("[data-copy]"); if (b) { navigator.clipboard.writeText(b.dataset.copy).then(() => toast("Copied", "ok"), () => toast("Copy failed - select the text manually", "err")); } });

/* ---------- Dashboard ---------- */
PAGES.dashboard = { title: "Dashboard", async render(root) {
  const [a, esc_, fus, docs, ints] = await Promise.all([API.get("/analytics/overview"), API.get("/escalations"), API.get("/follow-ups"), API.get("/knowledge/documents"), API.get("/integrations")]);
  const t = a.totals, r = a.rates;
  const steps = [[docs.length > 0, "Upload your first document", "knowledge"], [ints.groq.configured, "Connect the AI provider (GROQ_API_KEY on the server)", "integrations"], [true, "Try the assistants in Agent testing", "test"], [ints.whatsapp.configured || ints.email.configured, "Connect WhatsApp or email", "integrations"]];
  root.innerHTML = `${steps.some(s => !s[0]) ? `<div class="card" style="margin-bottom:1rem"><h3>Get set up</h3>${steps.map(s => `<div class="row small" style="margin:.2rem 0">${s[0] ? badge("done", STATUS_B) : badge("todo", { todo: "b-amber" })}<a href="#${s[2]}">${esc(s[1])}</a></div>`).join("")}</div>` : ""}
  <div class="grid g4">${kpi("Customers", t.customers)}${kpi("Conversations", t.conversations)}${kpi("Leads", t.leads, `${t.qualified_leads} qualified`)}${kpi("Converted", t.converted_leads, r.lead_conversion_rate + "% of leads")}${kpi("AI-resolved", t.ai_resolved, r.ai_resolution_rate + "% of conversations")}${kpi("Escalations", t.human_escalations, t.open_escalations + " open")}</div>
  <div class="grid g2" style="margin-top:1rem"><div class="card"><h3>Activity, last 14 days</h3><div class="canvas-wrap"><canvas id="c1"></canvas></div></div>
  <div class="card"><h3>Needs a human (${esc_.length})</h3>${esc_.length ? esc_.slice(0, 6).map(e => `<div class="list-item" onclick="location.hash='conversations/${e.conversation_id}'"><b>${esc(e.customer_name)}</b><div class="small muted">${esc(e.reason)} &middot; ${fmtDate(e.created_at)}</div></div>`).join("") : empty("Nothing waiting", "Escalated conversations appear here.")}</div></div>
  <div class="card" style="margin-top:1rem"><h3>Pending follow-ups</h3>${table(["Customer", "Action", "Channel", "Due"], fus.slice(0, 8).map(f => `<tr><td>${esc(f.customer_name || f.customer_email || "-")}</td><td>${esc(f.action)}</td><td>${esc(f.channel)}</td><td>${fmtDate(f.due_at)}</td></tr>`), empty("No pending follow-ups", "They are created when the sales agent captures a lead."))}</div>`;
  chart("c1", { type: "line", data: { labels: a.daily.labels.map(d => d.slice(5)), datasets: [{ label: "Conversations", data: a.daily.conversations, borderColor: "#0d5c4b", backgroundColor: "#0d5c4b22", fill: true, tension: .3 }, { label: "Leads", data: a.daily.leads, borderColor: "#f0b03a", tension: .3 }, { label: "Escalations", data: a.daily.escalations, borderColor: "#c4452b", tension: .3 }] }, options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
} };

/* ---------- Analytics ---------- */
PAGES.analytics = { title: "Analytics", async render(root) {
  const a = await API.get("/analytics/overview"), r = a.rates, t = a.totals;
  root.innerHTML = `<div class="grid g4">${kpi("Lead qualification rate", r.lead_qualification_rate + "%")}${kpi("Lead conversion rate", r.lead_conversion_rate + "%")}${kpi("AI resolution rate", r.ai_resolution_rate + "%")}${kpi("Escalation rate", r.escalation_rate + "%")}${kpi("Messages exchanged", t.messages)}</div>
  <p class="small muted">Calculated live from your database. Conversations started in Agent testing are excluded.</p>
  <div class="grid g2"><div class="card"><h3>Daily activity (14 days)</h3><div class="canvas-wrap"><canvas id="a1"></canvas></div></div><div class="card"><h3>Weekly activity (8 weeks)</h3><div class="canvas-wrap"><canvas id="a2"></canvas></div></div>
  <div class="card"><h3>Leads by status</h3><div class="canvas-wrap"><canvas id="a3"></canvas></div></div><div class="card"><h3>Conversations by channel</h3><div class="canvas-wrap"><canvas id="a4"></canvas></div></div></div>`;
  const pal = ["#0d5c4b", "#f0b03a", "#2c5fa8", "#c4452b", "#7f918d"];
  chart("a1", { type: "line", data: { labels: a.daily.labels.map(d => d.slice(5)), datasets: [{ label: "Conversations", data: a.daily.conversations, borderColor: pal[0], tension: .3 }, { label: "Leads", data: a.daily.leads, borderColor: pal[1], tension: .3 }] }, options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
  chart("a2", { type: "bar", data: { labels: a.weekly.labels, datasets: [{ label: "Conversations", data: a.weekly.conversations, backgroundColor: pal[0] }, { label: "Leads", data: a.weekly.leads, backgroundColor: pal[1] }] }, options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
  const st = Object.keys(a.leads_by_status), ch = Object.keys(a.conversations_by_channel);
  chart("a3", { type: "doughnut", data: { labels: st, datasets: [{ data: st.map(k => a.leads_by_status[k]), backgroundColor: pal }] } });
  chart("a4", { type: "doughnut", data: { labels: ch, datasets: [{ data: ch.map(k => a.conversations_by_channel[k]), backgroundColor: pal }] } });
} };

/* ---------- Business settings + team ---------- */
PAGES.business = { title: "Business settings", async render(root) {
  const [b, team] = await Promise.all([API.get("/business"), API.get("/team")]);
  const ro = isAdmin() ? "" : "disabled";
  root.innerHTML = `<div class="grid g2"><form class="card" id="bf" novalidate><h2>Business profile</h2><p class="small muted">The assistants use this to introduce your business.</p>
  ${field("Business name", "name", { value: b.name, required: true, min: 2 })}${field("Industry", "industry", { value: b.industry })}${field("Description", "description", { type: "textarea", value: b.description, hint: "What you sell and who you serve." })}
  ${field("Website", "website", { value: b.website })}${field("Public phone", "phone", { value: b.phone })}${field("Public email", "email", { value: b.email })}${field("Address", "address", { value: b.address })}
  ${field("Notification email", "notification_email", { value: b.notification_email, type: "email", hint: "Receives new-lead and escalation alerts (needs SMTP, see Integrations)." })}
  ${isAdmin() ? '<button class="btn" id="bsave">Save changes</button>' : '<p class="small muted">Only owners and admins can edit.</p>'}</form>
  <div class="card"><h2>Team</h2>${table(["Name", "Email", "Role", ""], team.map(u => `<tr><td>${esc(u.full_name)}</td><td>${esc(u.email)}</td><td>${badge(u.role)}</td><td>${isAdmin() && u.role !== "owner" ? `<button class="btn ghost sm" data-toggle="${u.id}" data-active="${u.is_active}">${u.is_active ? "Deactivate" : "Activate"}</button>` : (u.is_active ? "" : badge("inactive"))}</td></tr>`), "")}
  ${isAdmin() ? '<button class="btn ghost" id="addm" style="margin-top:.8rem">Add team member</button>' : ""}</div></div>`;
  root.querySelectorAll("#bf [disabled]").forEach(() => 0); if (ro) root.querySelectorAll("#bf input,#bf textarea").forEach(e => e.disabled = true);
  root.querySelector("#bf").onsubmit = async (e) => { e.preventDefault(); const f = e.target; if (!validateForm(f)) return; await withBusy(root.querySelector("#bsave"), async () => { try { await API.put("/business", Object.fromEntries(new FormData(f))); toast("Business profile saved", "ok"); } catch (x) { toast(x.message, "err"); } }); };
  root.querySelectorAll("[data-toggle]").forEach(b => b.onclick = async () => { try { await API.patch("/team/" + b.dataset.toggle, { is_active: b.dataset.active !== "true" }); PAGES.business.render(root); } catch (x) { toast(x.message, "err"); } });
  const am = root.querySelector("#addm"); if (am) am.onclick = () => dialog({ title: "Add team member", submit: "Add member", body: field("Full name", "full_name", { required: true, min: 2 }) + field("Email", "email", { type: "email", required: true }) + field("Temporary password", "password", { type: "password", required: true, min: 8 }) + field("Role", "role", { type: "select", options: [["agent", "Agent - CRM and conversations"], ["admin", "Admin - also settings and knowledge"]] }), onSubmit: async (v, d) => { await API.post("/team", v); d.close(); toast("Team member added", "ok"); PAGES.business.render(root); } });
} };

/* ---------- User settings ---------- */
PAGES.settings = { title: "User settings", async render(root) {
  const me = await API.get("/auth/me");
  root.innerHTML = `<div class="grid g2"><form class="card" id="pf" novalidate><h2>Profile</h2>${field("Full name", "full_name", { value: me.full_name, required: true, min: 2 })}<div class="field"><label>Email</label><input value="${esc(me.email)}" disabled></div><div class="field"><label>Role</label><div>${badge(me.role)}</div></div><button class="btn">Save profile</button></form>
  <form class="card" id="pw" novalidate><h2>Change password</h2>${field("Current password", "current_password", { type: "password", required: true })}${field("New password", "new_password", { type: "password", required: true, min: 8 })}<button class="btn">Update password</button></form></div>`;
  root.querySelector("#pf").onsubmit = async (e) => { e.preventDefault(); if (!validateForm(e.target)) return; try { const u = await API.put("/auth/me", Object.fromEntries(new FormData(e.target))); localStorage.setItem("aibiz_user", JSON.stringify(Object.assign(API.user(), u))); toast("Profile saved", "ok"); } catch (x) { toast(x.message, "err"); } };
  root.querySelector("#pw").onsubmit = async (e) => { e.preventDefault(); if (!validateForm(e.target)) return; try { await API.post("/auth/change-password", Object.fromEntries(new FormData(e.target))); e.target.reset(); toast("Password updated", "ok"); } catch (x) { toast(x.message, "err"); } };
} };
