// Management view: the models of models.json, with add / edit / reload
import { api } from "../api.js";
import { openModelForm } from "../components/model-form.js";
import { $, esc } from "../dom.js";
import { emit } from "../events.js";
import { state } from "../state.js";

export function renderModelsTable() {
  $("#cfgTable").innerHTML = `<thead><tr><th>Modèle</th><th>Type</th><th>Moteur</th><th>Fichier</th><th>Port</th><th></th></tr></thead>
    <tbody>${Object.entries(state.models).map(([id, m]) => `<tr>
      <td><b>${esc(m.name)}</b> <span class="meta" style="margin:0">${esc(id)}</span></td>
      <td>${esc(state.kinds[m.kind] || m.kind)}</td><td>${esc(m.engine)}</td>
      <td style="font-family:var(--mono);font-size:12px;word-break:break-all">${esc(m.config.file || "–")}</td>
      <td class="num">${m.port}</td>
      <td><button class="link" data-edit="${esc(id)}">Modifier</button></td></tr>`).join("")}</tbody>`;
}

export function bindModelsTable() {
  $("#cfgTable").addEventListener("click", e => {
    const id = e.target.closest("[data-edit]")?.dataset.edit;
    if (id) openModelForm(id);
  });
  $("#addModel").addEventListener("click", () => openModelForm(null));
  $("#reloadCfg").addEventListener("click", async () => {
    $("#cfgMsg").textContent = "";
    try { await api("/api/reload", {}); await emit("reload"); } catch (err) { $("#cfgMsg").textContent = err.message; }
  });
}
