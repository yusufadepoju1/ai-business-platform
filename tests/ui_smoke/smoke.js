const { JSDOM, VirtualConsole } = require("jsdom");
const BASE = "http://localhost:8000";
(async () => {
  const login = await (await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "demo@example.com", password: "DemoPass123!" }) })).json();
  const routes = ["dashboard","conversations","crm","customers","knowledge","agents","test","automations","integrations","analytics","business","settings"];
  let failures = 0;
  for (const r of routes) {
    const errors = []; const vc = new VirtualConsole(); vc.on("jsdomError", e => errors.push(e.message)); vc.on("error", e => errors.push(String(e)));
    const dom = await JSDOM.fromURL(`${BASE}/app.html#${r}`, { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole: vc,
      beforeParse(w) { w.fetch = (u, o) => fetch(new URL(u, BASE), o); w.localStorage.setItem("aibiz_token", login.access_token); w.localStorage.setItem("aibiz_user", JSON.stringify(login.user));
        w.Chart = class { constructor() {} destroy() {} }; w.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); }; w.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
        w.navigator.clipboard = { writeText: async () => {} }; } });
    await new Promise(res => setTimeout(res, 2500));
    const d = dom.window.document, view = d.getElementById("view"), txt = view.textContent.replace(/\s+/g, " ").trim();
    const bad = /Could not load this page/.test(txt) || !txt || view.querySelector(".spinner") || errors.length;
    console.log((bad ? "FAIL " : "ok   ") + r.padEnd(14) + "| " + d.getElementById("title").textContent + " | " + txt.slice(0, 90) + (errors.length ? " | ERR " + errors[0] : ""));
    if (bad) failures++;
    if (r === "crm") { const rows = d.querySelectorAll("#ll tr.click").length; console.log("     leads rows:", rows); if (!rows) failures++; d.querySelector("#ll tr.click").click(); await new Promise(r => setTimeout(r, 800)); console.log("     lead dialog open:", d.getElementById("dlg").hasAttribute("open")); }
    if (r === "customers") { console.log("     customer rows:", d.querySelectorAll("#cl tr.click").length); }
    if (r === "conversations") { console.log("     conversation items:", d.querySelectorAll("#cl .list-item").length); }
    dom.window.close();
  }
  process.exit(failures ? 1 : 0);
})();
