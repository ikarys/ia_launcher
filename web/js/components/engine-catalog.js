// Inference engines: the catalog (catalog/catalog.json) and background installs
import { api } from "../api.js";
import { $, esc } from "../dom.js";
import { emit } from "../events.js";
import { state } from "../state.js";

const STATES = { configured: ["Installé", "gpu"], present: ["Présent, à configurer", "partial"],
                 available: ["Non installé", "extra"] };
let catalog = [], timer = null;

// "install" link offered by a Hugging Face verdict (s: the suggested catalog engine)
export function installButton(s) {
  const what = s.state === "present" ? `Configurer ${s.label} (déjà présent)`
    : `Installer ${s.label} (~${s.disk_gb} Go, ~${s.minutes} min)`;
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
  if (c.job?.state === "running") return `<span class="meta" style="margin:0">Installation en cours…</span>`;
  const label = c.state === "configured" ? "Mettre à jour" : c.state === "present" ? "Configurer"
    : `Installer (~${c.disk_gb} Go, ~${c.minutes} min)`;
  return `<button class="${c.state === "available" ? "primary" : "link"}" data-install="${esc(c.id)}">${label}</button>`;
}

function jobHtml(job) {
  if (!job) return "";
  const color = { done: "var(--ok)", error: "var(--err)" }[job.state] || "inherit";
  return `<tr class="sub"><td colspan="4">
    <div class="meta" style="margin:0 0 4px;color:${color}">${esc(job.msg)}</div>
    <pre class="log">${esc(job.log)}</pre></td></tr>`;
}

function render() {
  $("#engTable").innerHTML = `<thead><tr><th>Moteur</th><th>Lance</th><th>État</th><th></th></tr></thead><tbody>${
    catalog.map(c => {
      const [label, cls] = STATES[c.state];
      const runs = [...c.file_ext, ...c.kinds.map(k => state.kinds[k] || k)];
      return `<tr>
        <td><b>${esc(c.label)}</b> <a class="meta" href="${esc(c.url)}" target="_blank" rel="noopener">site</a>
          <div class="meta" style="margin:2px 0 0">${esc(c.desc)}</div>
          <div class="meta" style="margin:2px 0 0;font-family:var(--mono)">${esc(c.dir)}</div></td>
        <td>${runs.map(t => `<span class="tag">${esc(t)}</span>`).join(" ")}</td>
        <td><span class="verdict v-${cls}">${label}</span></td>
        <td>${actionHtml(c)}</td></tr>${jobHtml(c.job)}`;
    }).join("")}</tbody>`;
  document.querySelectorAll("#engTable pre.log").forEach(p => p.scrollTop = p.scrollHeight);
}

export async function installEngine(id) {
  if (!catalog.some(x => x.id === id)) await loadEngines();
  const c = catalog.find(x => x.id === id);
  if (!c) return;
  const what = c.state === "available" ? `Installer ${c.label} dans ${c.dir} (~${c.disk_gb} Go, ~${c.minutes} min) ?`
    : c.state === "present" ? `Configurer ${c.label} (déjà présent dans ${c.dir}) ?`
    : `Mettre à jour ${c.label} (${c.dir}) ? Les modèles lancés ne sont pas touchés.`;
  if (!confirm(what)) return;
  $("#engMsg").textContent = "";
  try { await api(`/api/engines/install/${encodeURIComponent(id)}`, {}); }
  catch (err) { $("#engMsg").textContent = err.message; }
  $("#enginesSec").scrollIntoView({ behavior: "smooth" });
  await loadEngines();
  whenInstalled(id);
}

// once installed, engines.json changed: reload what the model form offers
function whenInstalled(id) {
  const t = setInterval(async () => {
    const c = catalog.find(x => x.id === id);
    if (c?.job?.state === "running") return;
    clearInterval(t);
    if (c?.job?.state === "done") await emit("reload");
  }, 3000);
}

export function bindEngineCatalog() {
  $("#engTable").addEventListener("click", e => {
    const id = e.target.closest("[data-install]")?.dataset.install;
    if (id) installEngine(id);
  });
}
