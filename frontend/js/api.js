/* Shared API client + helpers (no framework). */
const API = {
  token: () => localStorage.getItem("aibiz_token"),
  setSession(d) { localStorage.setItem("aibiz_token", d.access_token); localStorage.setItem("aibiz_user", JSON.stringify(d.user)); },
  user: () => { try { return JSON.parse(localStorage.getItem("aibiz_user")) } catch { return null } },
  logout() { localStorage.removeItem("aibiz_token"); localStorage.removeItem("aibiz_user"); location.href = "/login.html"; },
  async req(path, { method = "GET", body, form } = {}) {
    const headers = {};
    if (API.token()) headers.Authorization = "Bearer " + API.token();
    let payload;
    if (form) payload = form; else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
    let res;
    try { res = await fetch("/api" + path, { method, headers, body: payload }); }
    catch { throw new Error("Cannot reach the server. Check your connection and try again."); }
    let data = null;
    try { data = await res.json(); } catch { /* empty body */ }
    if (res.status === 401 && !path.startsWith("/auth/login") && !path.startsWith("/auth/register")) { API.logout(); throw new Error("Session expired"); }
    if (!res.ok) {
      let msg = data && data.detail;
      if (Array.isArray(msg)) msg = msg.map(e => (e.loc || []).slice(1).join(".") + ": " + e.msg).join("; ");
      throw new Error(msg || "Request failed (" + res.status + ")");
    }
    return data;
  },
  get: (p) => API.req(p), post: (p, b) => API.req(p, { method: "POST", body: b === undefined ? {} : b }),
  put: (p, b) => API.req(p, { method: "PUT", body: b }), patch: (p, b) => API.req(p, { method: "PATCH", body: b }),
  del: (p) => API.req(p, { method: "DELETE" }),
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDate = (s) => { if (!s) return "-"; if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += "Z"; const d = new Date(s); return isNaN(d) ? "-" : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); };
function toast(msg, type = "") {
  let box = document.querySelector(".toasts"); if (!box) { box = document.createElement("div"); box.className = "toasts"; box.setAttribute("aria-live", "polite"); document.body.appendChild(box); }
  const t = document.createElement("div"); t.className = "toast " + type; t.textContent = msg; box.appendChild(t); setTimeout(() => t.remove(), 4500);
}
function setFieldError(input, msg) {
  input.classList.toggle("invalid", !!msg);
  let e = input.parentElement.querySelector(".err"); if (!e) { e = document.createElement("div"); e.className = "err"; input.parentElement.appendChild(e); } e.textContent = msg || "";
}
function validateForm(form) {
  let ok = true;
  form.querySelectorAll("input,select,textarea").forEach(el => {
    let m = ""; if (el.required && !el.value.trim()) m = "This field is required.";
    else if (el.type === "email" && el.value && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(el.value)) m = "Enter a valid email address.";
    else if (el.minLength > 0 && el.value && el.value.length < el.minLength) m = "Use at least " + el.minLength + " characters.";
    setFieldError(el, m); if (m) ok = false;
  });
  return ok;
}
async function withBusy(btn, fn) { const t = btn.textContent; btn.disabled = true; btn.textContent = "Working..."; try { return await fn(); } finally { btn.disabled = false; btn.textContent = t; } }
