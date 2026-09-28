// Hugging Face repository browser: variants with a "does it run here?" verdict, alternatives
import { api } from "../api.js";
import { $, esc } from "../dom.js";
import { size } from "../format.js";
import { state } from "../state.js";
import { installButton } from "./engine-catalog.js";

const VERDICT = { installed: "Déjà installé", gpu: "Tient sur le GPU", partial: "GPU + RAM (lent)", no: "Trop gros",
  incompatible: "Incompatible", disk: "Disque plein", extra: "Optionnel" };

export function hardwareLine(hw) {
  return hw.gpu ? `Machine : ${hw.gpu.replace("NVIDIA GeForce ", "")} · ${size(hw.vram_mib * 2 ** 20)} VRAM `
    + `(${size(hw.vram_usable_mib * 2 ** 20)} utilisables) · génération ${hw.cc} · RAM ${size(hw.ram_mib * 2 ** 20)} `
    + `· ${hw.cpus} cœurs · disque ${size(hw.disk_free)} libres` : "Pas de GPU détecté";
}

const variantHtml = v => `
  <label>
    <input type="checkbox" data-files="${esc(JSON.stringify(v.files))}" data-verdict="${v.verdict}" data-size="${v.size}">
    <span class="name">${esc(v.name)}</span>
    ${v.quant ? `<span class="tag">${esc(v.quant)}</span>` : ""}
    <span class="verdict v-${v.verdict}">${VERDICT[v.verdict]}</span>
    <span class="meta" style="margin:0">${size(v.size)}</span>
    <span class="why">${esc(v.why)}${v.suggest ? ` ${installButton(v.suggest)}` : ""}</span>
  </label>`;

const alternativeHtml = a => `<div class="row">
  <span><b>${esc(a.repo)}</b> · ${esc(a.name)} <span class="tag">${esc(a.quant || "?")}</span> ${size(a.size)}
    <span class="meta" style="margin:0">· ${(a.downloads ?? 0).toLocaleString("fr-FR")} téléchargements</span></span>
  <button class="link" data-browse="${esc(a.repo)}">Voir le dépôt</button>
  <button class="link" data-quick="${esc(a.repo)}" data-files="${esc(JSON.stringify(a.files))}">Télécharger</button>
  <span class="why" style="padding-left:0">${esc(a.why)}</span></div>`;

// what to say under the variants when nothing runs here
function adviceHtml(d) {
  const main = d.variants.filter(v => v.verdict !== "extra");
  const fits = d.variants.some(v => ["gpu", "installed"].includes(v.verdict));
  const allIncompatible = main.length && main.every(v => v.verdict === "incompatible");
  if (d.alternatives.length) {
    const why = !main.length ? "" : allIncompatible ? "Aucune variante de ce dépôt n'est lançable ici (format)."
      : "Aucune variante de ce dépôt ne tient sur ton GPU.";
    return `<div class="alts"><b>${why} Versions de ${esc(d.base_searched)} qui tournent ici :</b>
      ${d.alternatives.map(alternativeHtml).join("")}</div>`;
  }
  if (fits || !main.length) return "";
  const smallest = main.reduce((a, v) => v.size < a.size ? v : a);
  if (allIncompatible) return `<div class="alts"><b>Aucune variante utilisable avec les moteurs installés.</b> ${esc(smallest.why)}</div>`;
  return `<div class="alts"><b>Rien ne tient sur ton GPU.</b> La plus petite variante (${esc(smallest.quant || smallest.name)},
    ${size(smallest.size)}) : ${esc(smallest.why)} Aucune autre version quantifiée compatible trouvée sur Hugging Face.</div>`;
}

function repoHtml(d) {
  const task = d.task ? ` · tâche <span class="tag">${esc(d.task)}</span> → section ${
    esc(state.kinds[d.kind] || "aucune (type à choisir à l'ajout)")}` : "";
  const files = d.variants.length ? `<div class="hf-files">${d.variants.map(variantHtml).join("")}</div>
    <div class="row" style="margin:8px 0">
      <button class="primary" id="hfDownload" data-repo="${esc(d.repo)}">Télécharger la sélection</button>
      <span class="meta" id="hfSel" style="margin:0"></span></div>`
    : `<p class="meta">Aucun fichier de modèle (gguf, safetensors, ninfer) dans ce dépôt.</p>`;
  return `
    <div class="meta" style="margin:0 0 6px">${esc(d.repo)} · commit <code>${esc(d.sha.slice(0, 7))}</code>
      · mis à jour ${esc((d.modified || "").slice(0, 10))}${d.gated ? " · <b>accès protégé</b>" : ""}${task}</div>
    ${files}${adviceHtml(d)}`;
}

export async function browse(repo) {
  $("#hfRepo").value = repo;
  $("#libMsg").textContent = "";
  $("#hfFiles").innerHTML = `<span class="meta">Analyse du dépôt et de ta machine…</span>`;
  try {
    const d = await api("/api/hf/info", { repo });
    $("#hwLine").textContent = hardwareLine(d.hardware);
    $("#hfFiles").innerHTML = repoHtml(d);
  } catch (err) { $("#hfFiles").innerHTML = ""; $("#libMsg").textContent = err.message; }
}

export const selectedVariants = () => [...document.querySelectorAll("#hfFiles input:checked")];

export function bindHfBrowser() {
  $("#hfForm").addEventListener("submit", e => { e.preventDefault(); browse($("#hfRepo").value.trim()); });
  $("#hfFiles").addEventListener("change", () => {
    const sel = selectedVariants();
    const total = sel.reduce((t, i) => t + +i.dataset.size, 0);
    $("#hfSel").textContent = sel.length ? `${sel.length} variante(s) · ${size(total)}` : "";
  });
}
