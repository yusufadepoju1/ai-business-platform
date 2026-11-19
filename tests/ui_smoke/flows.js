const { JSDOM, VirtualConsole } = require("jsdom");
const BASE = "http://localhost:8000"; const sleep = ms => new Promise(r => setTimeout(r, ms));
function mk(url, token) { const errors = []; const vc = new VirtualConsole(); vc.on("jsdomError", e => { if (!/fonts\.googleapis|chart\.js|jsdelivr/.test(e.message)) errors.push(e.message); });
  return JSDOM.fromURL(BASE + url, { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) { w.fetch = (u, o) => fetch(new URL(u, BASE), o); if (token) w.localStorage.setItem("aibiz_token", token); w.Chart = class { constructor() {} destroy() {} };
      w.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); }; w.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); }; } }).then(async d => { await sleep(1500); d.errors = errors; return d; }); }
(async () => {
  let fails = 0; const check = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
  // 1. register form: validation, then success -> token stored & redirect target
  let d = await mk("/register.html"); let w = d.window, D = w.document;
  D.getElementById("f").dispatchEvent(new w.Event("submit", { cancelable: true })); await sleep(200);
  check(D.querySelectorAll(".err").length >= 3 && D.getElementById("email").classList.contains("invalid"), "register: empty form shows validation errors");
  D.getElementById("business_name").value = "UI Test Co"; D.getElementById("full_name").value = "Ui Tester"; D.getElementById("email").value = "ui" + Date.now() + "@example.com"; D.getElementById("password").value = "UiTestPass123";
  D.getElementById("f").dispatchEvent(new w.Event("submit", { cancelable: true })); await sleep(2500);
  const token = w.localStorage.getItem("aibiz_token"); check(!!token, "register: account created and token stored"); w.close();
  // 2. login with wrong password shows message
  d = await mk("/login.html"); w = d.window; D = w.document; D.getElementById("email").value = "nobody@example.com"; D.getElementById("password").value = "wrongpassword";
  D.getElementById("f").dispatchEvent(new w.Event("submit", { cancelable: true })); await sleep(1500);
  check(/Incorrect email or password/.test(D.getElementById("msg").textContent), "login: wrong credentials show server error"); w.close();
  // 3. new empty tenant: empty states + agent test chat with no GROQ key
  d = await mk("/app.html#customers", token); w = d.window; D = w.document; await sleep(2000);
  check(/No customers/.test(D.getElementById("view").textContent), "customers: empty state for a new business");
  w.location.hash = "#test"; await sleep(1200);
  D.getElementById("ci").value = "Hello, do you ship abroad?"; D.getElementById("cf").dispatchEvent(new w.Event("submit", { cancelable: true })); await sleep(2500);
  const bubbles = [...D.querySelectorAll("#msgs .bubble")].map(b => b.textContent);
  check(bubbles.length === 2 && /temporarily unavailable/i.test(bubbles[1]), "agent test: with no API key the UI says the assistant is unavailable (no fake answer): " + JSON.stringify(bubbles[1]));
  check(/not configured|unavailable/i.test(D.getElementById("trace").textContent), "agent test: trace shows provider error");
  w.location.hash = "#knowledge"; await sleep(1500); check(/No documents yet/.test(D.getElementById("view").textContent), "knowledge: empty state");
  w.location.hash = "#customers"; await sleep(1200); D.getElementById("nc").click(); await sleep(300);
  D.getElementById("dform").dispatchEvent(new w.Event("submit", { cancelable: true })); await sleep(300);
  D.querySelector("#f_name").value = "Pat Example"; D.querySelector("#f_email").value = "pat@example.com";
  D.getElementById("dform").dispatchEvent(new w.Event("submit", { cancelable: true })); await sleep(1500);
  w.location.hash = "#customers"; await sleep(500); check(/Pat Example/.test(D.getElementById("view").textContent), "customers: add-customer dialog creates a record");
  check(d.errors.length === 0, "no JS errors in console" + (d.errors.length ? ": " + d.errors[0] : ""));
  w.close(); process.exit(fails ? 1 : 0);
})();
