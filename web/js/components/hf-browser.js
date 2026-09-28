// Hugging Face repository browser: variants with a "does it run here?" verdict, alternatives
import { api } from "../api.js";
import { $, esc } from "../dom.js";
import { count, size } from "../format.js";
import { t } from "../i18n.js";
import { state } from "../state.js";
import { installButton } from "./engine-catalog.js";

export function hardwareLine(hw) {
  if (!hw.gpu) return t("ui.hf.no_gpu");
  return t("ui.hf.hardware", { gpu: hw.gpu.replace("NVIDIA GeForce ", ""), vram: size(hw.vram_mib * 2 ** 20),
    usable: size(hw.vram_usable_mib * 2 ** 20), cc: hw.cc, ram: size(hw.ram_mib * 2 ** 20), cpus: hw.cpus,
    disk: size(hw.disk_free) });
}

const variantHtml = v => `
  <label>
    <input type="checkbox" data-files="${esc(JSON.stringify(v.files))}" data-verdict="${v.verdict}" data-size="${v.size}">
    <span class="name">${esc(v.name)}</span>
    ${v.quant ? `<span class="tag">${esc(v.quant)}</span>` : ""}
    <span class="verdict v-${v.verdict}">${esc(t("ui.verdict." + v.verdict))}</span>
    <span class="meta" style="margin:0">${size(v.size)}</span>
    <span class="why">${esc(v.why)}${v.suggest ? ` ${installButton(v.suggest)}` : ""}</span>
  </label>`;

const alternativeHtml = a => `<div class="row">
  <span><b>${esc(a.repo)}</b> · ${esc(a.name)} <span class="tag">${esc(a.quant || "?")}</span> ${size(a.size)}
    <span class="meta" style="margin:0">· ${esc(t("ui.hf.downloads", { n: count(a.downloads) }))}</span></span>
  <button class="link" data-browse="${esc(a.repo)}">${esc(t("ui.hf.view"))}</button>
  <button class="link" data-quick="${esc(a.repo)}" data-files="${esc(JSON.stringify(a.files))}">${esc(t("ui.hf.download"))}</button>
  <span class="why" style="padding-left:0">${esc(a.why)}</span></div>`;

// what to say under the variants when nothing runs here
function adviceHtml(d) {
  const main = d.variants.filter(v => v.verdict !== "extra");
  const fits = d.variants.some(v => ["gpu", "installed"].includes(v.verdict));
  const allIncompatible = main.length && main.every(v => v.verdict === "incompatible");
  if (d.alternatives.length) {
    const why = !main.length ? "" : t(allIncompatible ? "ui.hf.none_format" : "ui.hf.none_fits");
    return `<div class="alts"><b>${esc(why)} ${esc(t("ui.hf.alternatives", { base: d.base_searched }))}</b>
      ${d.alternatives.map(alternativeHtml).join("")}</div>`;
  }
  if (fits || !main.length) return "";
  const smallest = main.reduce((a, v) => v.size < a.size ? v : a);
  if (allIncompatible) return `<div class="alts"><b>${esc(t("ui.hf.none_usable"))}</b> ${esc(smallest.why)}</div>`;
  return `<div class="alts"><b>${esc(t("ui.hf.nothing_fits"))}</b> ${esc(t("ui.hf.smallest",
    { name: smallest.quant || smallest.name, size: size(smallest.size), why: smallest.why }))}</div>`;
}

function repoHtml(d) {
  const section = esc(d.kind && state.kinds[d.kind] ? t("ui.hf.section", { kind: state.kinds[d.kind] }) : t("ui.hf.no_section"));
  const task = d.task ? ` · ${esc(t("ui.hf.task"))} <span class="tag">${esc(d.task)}</span> → ${section}` : "";
  const files = d.variants.length ? `<div class="hf-files">${d.variants.map(variantHtml).join("")}</div>
    <div class="row" style="margin:8px 0">
      <button class="primary" id="hfDownload" data-repo="${esc(d.repo)}">${esc(t("ui.hf.download_selection"))}</button>
      <span class="meta" id="hfSel" style="margin:0"></span></div>`
    : `<p class="meta">${esc(t("ui.hf.no_files"))}</p>`;
  return `
    <div class="meta" style="margin:0 0 6px">${esc(d.repo)} · commit <code>${esc(d.sha.slice(0, 7))}</code>
      · ${esc(t("ui.hf.updated", { date: (d.modified || "").slice(0, 10) }))}${
      d.gated ? ` · <b>${esc(t("ui.hf.gated"))}</b>` : ""}${task}</div>
    ${files}${adviceHtml(d)}`;
}

export async function browse(repo) {
  $("#hfRepo").value = repo;
  $("#libMsg").textContent = "";
  $("#hfFiles").innerHTML = `<span class="meta">${esc(t("ui.hf.analysing"))}</span>`;
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
    const total = sel.reduce((sum, i) => sum + +i.dataset.size, 0);
    $("#hfSel").textContent = sel.length ? t("ui.hf.selected", { n: sel.length, size: size(total) }) : "";
  });
}
