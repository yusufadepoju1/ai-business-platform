/* Router + shell bootstrap. Loaded last. */
(async function () {
  if (!API.token()) { location.href = "/login.html"; return; }
  try { state.user = await API.get("/auth/me"); } catch { return; }
  localStorage.setItem("aibiz_user", JSON.stringify(state.user));
  document.getElementById("who").textContent = state.user.full_name + " - " + state.user.business_name;
  document.getElementById("demo").hidden = !state.user.is_demo;
  document.getElementById("out").onclick = () => API.logout();
  const side = document.getElementById("side");
  document.getElementById("menu").onclick = () => side.classList.toggle("open");
  document.getElementById("nav").innerHTML = NAV.map(([k, l]) => k === "sep" ? `<div class="sep">${l}</div>` : `<a href="#${k}" data-k="${k}">${l}</a>`).join("");
  let seq = 0;
  async function route() {
    const [key, arg] = (location.hash.slice(1) || "dashboard").split("/");
    const page = PAGES[key] || PAGES.dashboard, k = PAGES[key] ? key : "dashboard";
    side.classList.remove("open"); destroyCharts();
    document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.dataset.k === k));
    document.getElementById("title").textContent = page.title; document.title = page.title + " - Autopilot";
    const root = document.getElementById("view"); root.innerHTML = spinner(); const my = ++seq;
    try { await page.render(root, arg); } catch (e) { if (my === seq) root.innerHTML = `<div class="card">${empty("Could not load this page", e.message)}<div style="text-align:center"><button class="btn ghost" onclick="location.reload()">Try again</button></div></div>`; }
  }
  window.addEventListener("hashchange", route); route();
})();
