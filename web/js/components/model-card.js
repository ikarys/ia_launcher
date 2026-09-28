// A model card: state, usage, options / profiles, start / stop / logs / engine update
import { api } from "../api.js";
import { $, esc } from "../dom.js";
import { emit } from "../events.js";
import { dur, gb, initials } from "../format.js";
import { seg, state } from "../state.js";
import { openModelForm } from "./model-form.js";
import { fill, spark, track } from "./sparkline.js";

const STATE = { stopped: "Arrêté", starting: "Chargement…", ready: "Prêt", stopping: "Arrêt…", error: "Erreur" };
const VRAM_HOW = { live: "VRAM (mesurée)", estimate: "VRAM (estimée)", load: "VRAM (au chargement)",
                   shared: "VRAM (partagée)", cpu: "VRAM · tourne sur CPU" };
const openLogs = new Set();

export function cardHtml(id, m, hidden) {
  return `
    <article class="panel card" id="card-${id}"${hidden ? " hidden" : ""} style="--c:${seg(id)}">
      <div class="card-head">
        <span class="avatar">${esc(initials(m.name))}</span>
        <div>
          <h2>${esc(m.name)}</h2>
          <div class="engine">${esc(m.engine)} · port ${m.port}${m.task ? ` · ${esc(m.task)}` : ""}</div>
        </div>
        <span class="pill" data-k="pill"><span class="dot"></span><span data-k="state">–</span></span>
      </div>
      <p class="desc">${esc(m.desc)}</p>
      <div class="metrics off" data-k="metrics">
        <div class="metric"><div class="m"><i data-k="vramM"></i></div><b data-k="vram">–</b><span data-k="vramHow">VRAM</span></div>
        <div class="metric"><div class="m"><i data-k="ramM"></i></div><b data-k="ram">–</b><span>RAM</span></div>
        <div class="metric"><div data-k="cpuSpark"></div><b data-k="cpu">–</b><span data-k="cpuSub">CPU</span></div>
        <div class="metric"><b data-k="uptime">–</b><span>en route depuis</span></div>
      </div>
      <div class="opts">${optionsHtml(m)}</div>
      <div class="endpoint" data-k="endpoint"></div>
      <div class="actions">
        <button class="primary" data-act="start">Démarrer</button>
        <button class="danger" data-act="stop">Arrêter</button>
        <button class="link" data-act="logs">Logs</button>
        ${m.repo ? `<button class="link" data-act="update">Vérifier MAJ</button>` : ""}
        <button class="link" data-act="edit">Modifier</button>
      </div>
      <div class="msg" data-k="msg"></div>
      <div class="meta" data-k="update" hidden></div>
      <div class="meta" data-k="upgrade" hidden></div>
      <pre class="log" data-k="log" hidden></pre>
    </article>`;
}

function optionsHtml(m) {
  if (!m.options.length) return "";
  return `
    <label>Profil
      <select data-profile>${Object.keys(m.profiles).map(p => `<option>${esc(p)}</option>`).join("")
        }<option value="">personnalisé</option></select>
    </label>${m.options.map(o => `
    <label>${esc(o.label)}
      <select data-opt="${o.key}">${o.choices.map(([v, l]) =>
        `<option value="${esc(v)}"${v === o.default ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
    </label>`).join("")}
    <button class="link" data-act="saveprof">Enregistrer le profil…</button>
    <button class="link" data-act="delprof">Supprimer le profil</button>`;
}

// profile = a set of option values: picking one fills the menus, touching a menu resyncs the profile
function applyProfile(card, p) {
  for (const [k, v] of Object.entries(p || {})) $(`[data-opt="${k}"]`, card).value = v;
}

function syncProfile(card, m) {
  const sel = $("[data-profile]", card);
  if (!sel) return;
  sel.value = Object.keys(m.profiles).find(n =>
    Object.entries(m.profiles[n]).every(([k, v]) => $(`[data-opt="${k}"]`, card).value === v)) ?? "";
}

const chosenOptions = card => Object.fromEntries(
  [...card.querySelectorAll("[data-opt]")].map(s => [s.dataset.opt, s.value]));

export function bindCard(id) {
  const card = $("#card-" + id), m = state.models[id];
  applyProfile(card, Object.values(m.profiles)[0]);
  card.addEventListener("change", e => {
    if (e.target.matches("[data-profile]")) applyProfile(card, m.profiles[e.target.value]);
    else if (e.target.matches("[data-opt]")) syncProfile(card, m);
  });
  card.addEventListener("click", async e => {
    const act = e.target.closest("button")?.dataset.act;
    if (!act) return;
    $("[data-k=msg]", card).textContent = "";
    await (ACTIONS[act] || startStop)(id, card, e.target, act);
  });
}

const showError = (card, err) => { $("[data-k=msg]", card).textContent = err.message; };

async function saveOrDeleteProfile(id, card, button, act) {
  const cur = $("[data-profile]", card).value;
  const name = act === "saveprof" ? prompt("Nom du profil (un nom existant est remplacé) :", cur) : cur;
  if (!name || (act === "delprof" && !confirm(`Supprimer le profil « ${name} » ?`))) return;
  try {
    await api(`/api/profile/${id}`, { name, opts: act === "saveprof" ? chosenOptions(card) : null });
    await emit("reload", id);
    if (act === "saveprof") {
      const c = $("#card-" + id);
      $("[data-profile]", c).value = name;
      applyProfile(c, state.models[id].profiles[name]);
    }
  } catch (err) { showError(card, err); }
}

function toggleLogs(id, card) {
  openLogs.has(id) ? openLogs.delete(id) : openLogs.add(id);
  $("[data-k=log]", card).hidden = !openLogs.has(id);
  if (openLogs.has(id)) refreshLog(id);
}

async function checkUpdate(id, card, button) {
  const out = $("[data-k=update]", card);
  button.disabled = true;
  out.hidden = false;
  out.textContent = "git fetch…";
  try {
    const u = await api(`/api/check/${id}`, {});
    out.innerHTML = u.behind.length
      ? `<b style="color:var(--warn)">${u.behind.length} commit(s) de retard</b> sur ${esc(u.branch)} (local ${esc(u.current)}) :`
        + `<pre class="log">${esc(u.behind.join("\n"))}</pre>`
        + `<div class="actions" style="margin-top:8px"><button data-act="upgrade">Mettre à jour (pull + compilation)</button></div>`
      : `À jour : ${esc(u.current)} = ${esc(u.branch)}`;
  } catch (err) { out.textContent = ""; showError(card, err); }
  button.disabled = false;
}

async function upgrade(id, card) {
  if (!confirm(`Mettre à jour ${state.models[id].engine} ? Le modèle lancé continue de tourner ; la nouvelle version servira au prochain démarrage.`)) return;
  try {
    await api(`/api/update/${id}`, {});
    $("[data-k=update]", card).hidden = true;
  } catch (err) { showError(card, err); }
  emit("poll");
}

async function startStop(id, card, button, act) {
  if (act === "stop" && !confirm(`Arrêter ${state.models[id].name} ?`)) return;
  button.disabled = true;
  try {
    await api(`/api/${act}/${id}`, act === "start" ? chosenOptions(card) : {});
    if (act === "start") { openLogs.add(id); $("[data-k=log]", card).hidden = false; }
  } catch (err) { showError(card, err); }
  emit("poll");
}

const ACTIONS = {
  edit: id => openModelForm(id),
  saveprof: saveOrDeleteProfile,
  delprof: saveOrDeleteProfile,
  logs: toggleLogs,
  update: checkUpdate,
  upgrade,
};

async function refreshLog(id) {
  const pre = $(`#card-${id} [data-k=log]`);
  if (!pre) return;
  const { log } = await api(`/api/logs/${id}`);
  const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  const s = state.last?.models[id];
  pre.textContent = log || (s?.managed === false && s?.pids.length
    ? "Lancé en dehors du launcher (raccourci Windows) : les logs sont dans sa fenêtre PowerShell."
    : "Pas encore de logs.");
  if (atBottom) pre.scrollTop = pre.scrollHeight;
}

// refresh a card from /api/status (st) for its model (s)
export function updateCard(id, s, st) {
  const card = $("#card-" + id), m = state.models[id];
  const running = s.pids.length > 0;
  $("[data-k=pill]", card).className = "pill " + s.state;
  card.classList.remove("stopped", "starting", "ready", "stopping", "error");
  card.classList.add(s.state);
  $("[data-k=state]", card).textContent = STATE[s.state] + (s.state === "ready" && !s.managed ? " (externe)" : "");
  updateMetrics(id, card, s, st, running);
  const lan = st.lan_ip ? `  ·  LAN <code>http://${st.lan_ip}:${m.port}${m.endpoint}</code>` : "";
  $("[data-k=endpoint]", card).innerHTML = s.state === "ready"
    ? `Local <code>http://127.0.0.1:${m.port}${m.endpoint}</code>${lan}` : "";
  card.querySelectorAll("[data-opt]").forEach(sel => {
    sel.disabled = running;
    if (running && s.opts) sel.value = s.opts[sel.dataset.opt] ?? sel.value;
  });
  const prof = $("[data-profile]", card);
  if (prof) { prof.disabled = running; if (running) syncProfile(card, m); }
  $("[data-act=start]", card).disabled = running || s.state === "stopping";
  $("[data-act=stop]", card).disabled = !running || s.state === "stopping";
  if (s.error) $("[data-k=msg]", card).textContent = s.error;
  updateUpgrade(card, s.update);
  if (openLogs.has(id)) refreshLog(id);
}

function updateMetrics(id, card, s, st, running) {
  const g = st.gpu;
  $("[data-k=metrics]", card).classList.toggle("off", !running);
  $("[data-k=vram]", card).textContent = !running ? "–" : s.vram_how === "shared" ? "?" : gb(s.vram_mib);
  $("[data-k=vramHow]", card).textContent = running ? VRAM_HOW[s.vram_how] || "VRAM" : "VRAM";
  $("[data-k=ram]", card).textContent = running ? gb(s.rss_mib) : "–";
  $("[data-k=cpu]", card).textContent = running ? Math.round(s.cpu_machine_pct) + " %" : "–";
  fill($("[data-k=vramM]", card), running && g && s.vram_how !== "shared" ? s.vram_mib / g.total * 100 : 0);
  fill($("[data-k=ramM]", card), running ? s.rss_mib / st.ram.total_mib * 100 : 0);
  const ch = track("cpu-" + id, running ? s.cpu_machine_pct : 0);
  spark($("[data-k=cpuSpark]", card), ch, Math.max(25, ...ch));
  $("[data-k=cpuSub]", card).textContent = running ? `CPU · ${(s.cpu_pct / 100).toFixed(1).replace(".", ",")} cœur(s)` : "CPU";
  $("[data-k=uptime]", card).textContent = running ? dur(s.uptime_s) : "–";
}

// engine update running / done / failed, with its log
function updateUpgrade(card, u) {
  const up = $("[data-k=upgrade]", card);
  up.hidden = !u;
  if (!u) return;
  const color = { running: "var(--warn)", done: "var(--ok)", error: "var(--err)" }[u.state];
  const pre = $("pre", up), atBottom = !pre || pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  up.innerHTML = `<b style="color:${color}">${esc(u.msg)}</b>` + (u.log ? `<pre class="log">${esc(u.log)}</pre>` : "");
  if (atBottom) $("pre", up)?.scrollTo(0, 1e9);
}
