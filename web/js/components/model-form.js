// Add / edit a model (the launcher writes models.json)
import { api } from "../api.js";
import { $, esc } from "../dom.js";
import { emit } from "../events.js";
import { size } from "../format.js";
import { state } from "../state.js";

const FIELDS = ["name", "kind", "task", "engine", "desc", "file", "port"];
let editing = null;  // model id, or null when adding

// value shown in a text field: fixed value, or the menu's values joined by commas
const fmt = v => v == null ? "" : Array.isArray(v) ? v.map(x => Array.isArray(x) ? x[0] : x).join(", ") : String(v);

// params with fixed values (vision, flash attention...) -> a menu: one value, or "choice on the card"
function paramFields(engine, params) {
  $("#paramFields").innerHTML = Object.entries(state.engines[engine].params).map(([k, p]) => {
    const v = params?.[k];
    const field = p.values ? `<select data-param="${esc(k)}">
        <option value="">défaut du moteur</option>
        ${p.values.map(([x, l]) => `<option value="${esc(x)}"${v === x ? " selected" : ""}>${esc(l)}</option>`).join("")}
        <option value="*"${Array.isArray(v) ? " selected" : ""}>au choix sur la carte</option></select>`
      : `<input data-param="${esc(k)}" value="${esc(fmt(v))}" placeholder="défaut du moteur">`;
    return `<label>${esc(p.label)} <span class="hint">${esc(k)}</span>${field}</label>`;
  }).join("");
  $("#fileField").hidden = !state.engines[engine].needs_file;
}

export function openModelForm(id, preset = {}) {
  editing = id;
  const c = id ? state.models[id].config
    : { kind: "llm", engine: Object.keys(state.engines)[0], port: 8000, params: {}, ...preset };
  const f = $("#modelForm");
  $("#modelTitle").textContent = id ? `Modifier ${c.name}` : "Ajouter un modèle";
  $("#engineSel").innerHTML = Object.entries(state.engines).map(([k, e]) => `<option value="${esc(k)}">${esc(e.label)}</option>`).join("");
  $("#kindSel").innerHTML = Object.entries(state.kinds).map(([k, l]) => `<option value="${esc(k)}">${esc(l)}</option>`).join("");
  $("#vramInfo").textContent = id
    ? `${size(state.models[id].vram_mib * 2 ** 20)}${c.vram_mib ? " (fixée dans models.json)" : ""}`
    : "calculée à l'enregistrement";
  $("#fileList").innerHTML = (state.lib?.items || []).flatMap(it => it.files.filter(x => x.path))
    .map(x => `<option value="${esc(state.lib.dir + "/" + x.path)}">`).join("");
  $("#taskList").innerHTML = Object.keys(state.taskKind).map(t => `<option value="${esc(t)}">`).join("");
  for (const k of FIELDS) f.elements[k].value = c[k] ?? "";
  f.elements.id.value = id || "";
  f.elements.id.disabled = !!id;
  paramFields(c.engine, c.params);
  $("#modelDelete").hidden = !id;
  $("#modelMsg").textContent = "";
  $("#modelDlg").showModal();
}

// form -> models.json entry; params keep the menu labels they already had
function readForm(f) {
  const el = f.elements;
  const old = editing ? state.models[editing].config.params || {} : {};
  const params = {};
  const body = { name: el.name.value.trim(), kind: el.kind.value, engine: el.engine.value,
    desc: el.desc.value.trim(), task: el.task.value.trim(), port: +el.port.value, params };
  f.querySelectorAll("[data-param]").forEach(inp => {
    const k = inp.dataset.param, t = inp.value.trim();
    if (!t) return;
    if (t === "*") { params[k] = Array.isArray(old[k]) ? old[k] : state.engines[body.engine].params[k].values.map(x => x[0]); return; }
    if (k in old && fmt(old[k]) === t) { params[k] = old[k]; return; }
    const vals = t.split(",").map(v => v.trim()).filter(Boolean);
    params[k] = vals.length > 1 ? vals : vals[0];
  });
  if (state.engines[body.engine].needs_file) body.file = el.file.value.trim();
  return body;
}

const newId = el => el.id.value.trim() || el.name.value.toLowerCase().normalize("NFD")
  .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");

async function submit(e) {
  e.preventDefault();
  const f = e.target;
  const id = editing || newId(f.elements);
  if (!editing && state.models[id]) { $("#modelMsg").textContent = `L'identifiant « ${id} » existe déjà.`; return; }
  try {
    await api(`/api/model/${id}`, readForm(f));
    $("#modelDlg").close();
    await emit("reload", id);
  } catch (err) { $("#modelMsg").textContent = err.message; }
}

async function remove() {
  if (!confirm(`Retirer ${state.models[editing].name} du launcher ? (le fichier du modèle n'est pas supprimé)`)) return;
  try {
    await api(`/api/model/${editing}/delete`, {});
    $("#modelDlg").close();
    await emit("reload");
  } catch (err) { $("#modelMsg").textContent = err.message; }
}

export function bindModelForm() {
  $("#engineSel").addEventListener("change", e => paramFields(e.target.value,
    editing && state.models[editing].config.engine === e.target.value ? state.models[editing].config.params : {}));
  $("#modelForm").elements.task.addEventListener("change", e => {
    const k = state.taskKind[e.target.value.trim()];
    if (k) $("#modelForm").elements.kind.value = k;
  });
  $("#modelCancel").addEventListener("click", () => $("#modelDlg").close());
  $("#modelForm").addEventListener("submit", submit);
  $("#modelDelete").addEventListener("click", remove);
}
