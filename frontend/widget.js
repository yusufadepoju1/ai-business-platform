/* Embeddable chat widget. Usage: <script src="https://YOUR_HOST/widget.js" data-key="pk_..." async></script> */
(function () {
  var s = document.currentScript; if (!s) return;
  var key = s.getAttribute("data-key"); if (!key) return console.error("Autopilot widget: data-key missing");
  var base = new URL(s.src).origin, sidKey = "autopilot_sid_" + key;
  var sid = localStorage.getItem(sidKey); if (!sid) { sid = "w" + Math.random().toString(36).slice(2) + Date.now().toString(36); localStorage.setItem(sidKey, sid); }
  var last = 0, open = false, title = "Chat with us";
  var css = ".apw{position:fixed;right:18px;bottom:18px;z-index:2147483000;font-family:system-ui,sans-serif}.apw button.t{width:56px;height:56px;border-radius:50%;border:0;background:#0d5c4b;color:#fff;font-size:24px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.25)}.apw .p{display:none;width:340px;max-width:calc(100vw - 36px);height:460px;max-height:calc(100vh - 100px);background:#fff;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.25);flex-direction:column;overflow:hidden;margin-bottom:10px}.apw.o .p{display:flex}.apw .h{background:#0d5c4b;color:#fff;padding:12px 14px;font-weight:600}.apw .m{flex:1;overflow:auto;padding:10px;background:#f6f8f7;display:flex;flex-direction:column;gap:8px}.apw .b{padding:8px 11px;border-radius:12px;max-width:85%;font-size:14px;line-height:1.4;white-space:pre-wrap}.apw .u{align-self:flex-end;background:#0d5c4b;color:#fff}.apw .a{align-self:flex-start;background:#fff;border:1px solid #dfe5e0}.apw form{display:flex;border-top:1px solid #dfe5e0}.apw input{flex:1;border:0;padding:12px;font-size:14px;outline:none}.apw form button{border:0;background:none;color:#0d5c4b;font-weight:700;padding:0 14px;cursor:pointer}";
  var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
  var w = document.createElement("div"); w.className = "apw";
  w.innerHTML = '<div class="p" role="dialog" aria-label="Chat"><div class="h"></div><div class="m" aria-live="polite"></div><form><input placeholder="Type your message" maxlength="2000" aria-label="Message"><button>Send</button></form></div><button class="t" aria-label="Open chat">&#128172;</button>';
  document.body.appendChild(w);
  var box = w.querySelector(".m"), inp = w.querySelector("input"), form = w.querySelector("form");
  function add(t, who) { var d = document.createElement("div"); d.className = "b " + who; d.textContent = t; box.appendChild(d); box.scrollTop = box.scrollHeight; }
  w.querySelector(".t").onclick = function () { open = !open; w.classList.toggle("o", open); if (open) inp.focus(); };
  fetch(base + "/api/public/widget-config?key=" + encodeURIComponent(key)).then(r => r.json()).then(function (c) {
    if (c.business_name) { title = c.business_name; w.querySelector(".h").textContent = title; } if (c.greeting) add(c.greeting, "a");
  }).catch(function () { w.style.display = "none"; });
  form.onsubmit = function (e) {
    e.preventDefault(); var t = inp.value.trim(); if (!t) return; inp.value = ""; add(t, "u");
    fetch(base + "/api/public/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: key, session_id: sid, message: t }) })
      .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.detail || "error"); return d; }); })
      .then(function (d) { add(d.reply, "a"); last = Math.max(last, d.last_message_id || 0); })
      .catch(function () { add("Sorry, something went wrong. Please try again.", "a"); });
  };
  setInterval(function () { if (!open) return;
    fetch(base + "/api/public/chat/poll?key=" + encodeURIComponent(key) + "&session_id=" + sid + "&after_id=" + last).then(r => r.json()).then(function (d) {
      (d.messages || []).forEach(function (m) { add(m.content, "a"); last = Math.max(last, m.id); }); }).catch(function () {});
  }, 5000);
})();
