// Inference engines (Settings view): the catalog (catalog/catalog.json) and background installs
import { api } from "../api.js";
import { $, esc } from "../dom.js";
import { emit } from "../events.js";
import { t } from "../i18n.js";
import { state } from "../state.js";

const STATE_CLASS = { configured: "gpu", present: "partial", available: "extra" };
let catalog = [], timer = null;

// "install" link offered by a Hugging Face verdict (s: the suggested catalog engine)
export function installButton(s) {
  const what = s.state === "present" ? t("ui.eng.configure_named", { label: s.label })
    : t("ui.eng.install_named", { label: s.label, disk: s.disk_gb, min: s.minutes });
  return `<button class="link" data-install="${esc(s.id)}">${esc(what)}</button>`;
}

export async function loadEngines() {
  clearTimeout(timer);
  try { catalog = (await api("/api/engines")).catalog; } catch (err) { $("#engMsg").textContent = err.message; return; }
  render();
  if (catalog.some(c => c.job?.state === "running")) timer = setTimeout(loadEngines, 3000);
}

function actionHtml(c) {
  if (!c.compatible) return `<span class="meta" style="margin:0">${esc(c.why)}</span>`;
  if (c.job?.state === "running") return `<span class="meta" style="margin:0">${esc(t("ui.eng.installing"))}</span>`;
  const label = c.state === "configured" ? t("ui.eng.update") : c.state === "present" ? t("ui.eng.configure")
    : t("ui.eng.install", { disk: c.disk_gb, min: c.minutes });
  return `<button class="${c.state === "available" ? "primary" : "link"}" data-install="${esc(c.id)}">${esc(label)}</button>`;
}

function jobHtml(job) {
  if (!job) return "";
  const color = { done: "var(--ok)", error: "var(--err)" }[job.state] || "inherit";
  return `<tr class="sub"><td colspan="4">
    <div class="meta" style="margin:0 0 4px;color:${color}">${esc(job.msg)}</div>
    <pre class="log">${esc(job.log)}</pre></td></tr>`;
}

function render() {
  const head = ["engine", "runs", "state"].map(c => `<th>${esc(t("ui.col." + c))}</th>`).join("");
  $("#engTable").innerHTML = `<thead><tr>${head}<th></th></tr></thead><tbody>${
    catalog.map(c => {
      const runs = [...c.file_ext, ...c.kinds.map(k => state.kinds[k] || k)];
      return `<tr>
        <td><b>${esc(c.label)}</b> <a class="meta" href="${esc(c.url)}" target="_blank" rel="noopener">${esc(t("ui.eng.site"))}</a>
          <div class="meta" style="margin:2px 0 0">${esc(c.desc)}</div>
          <div class="meta" style="margin:2px 0 0;font-family:var(--mono)">${esc(c.dir)}</div></td>
        <td>${runs.map(x => `<span class="tag">${esc(x)}</span>`).join(" ")}</td>
        <td><span class="verdict v-${STATE_CLASS[c.state]}">${esc(t("ui.eng.state." + c.state))}</span></td>
        <td>${actionHtml(c)}</td></tr>${jobHtml(c.job)}`;
    }).join("")}</tbody>`;
  document.querySelectorAll("#engTable pre.log").forEach(p => p.scrollTop = p.scrollHeight);
}

function confirmText(c) {
  const vars = { label: c.label, dir: c.dir, disk: c.disk_gb, min: c.minutes };
  return t({ available: "ui.eng.confirm_install", present: "ui.eng.confirm_configure" }[c.state]
    || "ui.eng.confirm_update", vars);
}

// msg: where to report errors / progress (the engines table, or the view the install came from)
export async function installEngine(id, msg = $("#engMsg")) {
  if (!catalog.some(x => x.id === id)) await loadEngines();
  const c = catalog.find(x => x.id === id);
  if (!c || !confirm(confirmText(c))) return;
  msg.textContent = "";
  try {
    await api(`/api/engines/install/${encodeURIComponent(id)}`, {});
    if (msg.id !== "engMsg") msg.innerHTML = `${esc(t("ui.eng.follow"))} <a href="/settings">${esc(t("ui.nav.settings"))}</a>`;
  } catch (err) { msg.textContent = err.message; return; }
  await loadEngines();
  whenInstalled(id);
}

// once installed, engines.json changed: reload what the model form offers
// (the catalog refreshes itself while a job runs)
function whenInstalled(id) {
  const watch = setInterval(async () => {
    const c = catalog.find(x => x.id === id);
    if (c?.job?.state === "running") return;
    clearInterval(watch);
    if (c?.job?.state === "done") await emit("reload");
  }, 3000);
}

export function bindEngineCatalog() {
  $("#engTable").addEventListener("click", e => {
    const id = e.target.closest("[data-install]")?.dataset.install;
    if (id) installEngine(id);
  });
}
