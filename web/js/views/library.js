// Models view: the models folder (downloads, Hugging Face cache, files put by hand)
import { api } from "../api.js";
import { installEngine } from "../components/engine-catalog.js";
import { browse, hardwareLine, selectedVariants } from "../components/hf-browser.js";
import { openModelForm } from "../components/model-form.js";
import { $, esc } from "../dom.js";
import { size } from "../format.js";
import { t } from "../i18n.js";
import { state } from "../state.js";

const COLUMNS = ["model", "quant", "version", "date", "size", "used_by"];
let timer = null;

export async function loadLibrary() {
  clearTimeout(timer);
  try { state.lib = await api("/api/library"); } catch (err) { $("#libMsg").textContent = err.message; return; }
  render();
  if (state.lib.downloads.some(d => d.state === "running")) timer = setTimeout(loadLibrary, 2000);
}

// engine for a weights file: from the engines' file_ext, installed engines first (null: none).
// When several engines load the file, the one whose kinds cover the model's kind wins (a TTS
// repository suggests the TTS engine, not the first safetensors server).
function engineFor(name, kind) {
  const fits = Object.entries(state.engines).filter(([, e]) => e.file_ext.some(x => name.endsWith(x)));
  const byKind = kind ? fits.filter(([, e]) => e.kinds?.includes(kind)) : [];
  const pool = byKind.length ? byKind : fits;
  return (pool.find(([, e]) => e.installed) || pool[0] || [null])[0];
}

function downloadHtml(d) {
  const status = d.state === "running" ? `
    <div class="bar"><span style="width:${Math.min(100, d.done / d.total * 100)}%;background:var(--accent)"></span></div>
    <div class="meta">${size(d.done)} / ${size(d.total)} · <button class="link" data-cancel="${d.id}">${esc(t("ui.dl.cancel"))}</button></div>`
    : `<div class="meta" style="color:${d.state === "done" ? "var(--ok)" : "var(--err)"}">${
        esc({ done: t("ui.dl.done"), cancelled: t("ui.dl.cancelled") }[d.state] || d.msg)}</div>`;
  return `<div class="dl-row"><div><b>${esc(d.repo)}</b> <span class="meta">${esc(d.files.join(", "))}</span></div>${status}</div>`;
}

const usedHtml = u => u?.length ? `<span class="used">● ${esc(u.join(", "))}</span>` : "";
// files used by a model can't be deleted: the button says why instead of disappearing
function deleteHtml(path, label, usedBy) {
  if (!path) return "";
  if (usedBy?.length) {
    return `<button class="link" disabled title="${esc(t("ui.lib.delete_blocked", { models: usedBy.join(", ") }))}">${esc(t("ui.lib.delete"))}</button>`;
  }
  return `<button class="link" data-del="${esc(path)}" data-label="${esc(label)}" style="color:var(--err)">${esc(t("ui.lib.delete"))}</button>`;
}
const useHtml = (x, task) => x.path && engineFor(x.name, state.taskKind[task]) && !x.used_by?.length
  ? `<button class="link" data-use="${esc(x.path)}" data-task="${esc(task || "")}">${esc(t("ui.lib.add_model"))}</button>` : "";

function itemHtml(it) {
  const single = it.files.length === 1 && it.files[0].path === it.path;
  const version = [it.sha && `<code>${esc(it.sha)}</code>`, it.hf_date && `HF ${esc(it.hf_date)}`].filter(Boolean).join(" · ") || "–";
  const head = `<tr>
    <td><b>${esc(it.repo || it.path)}</b> <span class="tag">${esc(t("ui.src." + it.source))}</span>${
      it.task ? ` <span class="tag">${esc(it.task)}</span>` : ""}${
      it.repo && it.source !== "hf_cache" ? `<div class="meta" style="margin:0">${esc(it.path)}</div>` : ""}</td>
    <td>${single ? esc(it.files[0].quant || "–") : ""}</td>
    <td>${version}</td>
    <td class="num">${esc(single ? it.files[0].downloaded || it.date : it.date)}</td>
    <td class="num">${size(it.size)}</td>
    <td>${usedHtml(it.used_by)}</td>
    <td>${single ? useHtml(it.files[0], it.task) : ""} ${deleteHtml(it.path, it.repo || it.path, it.used_by)}</td></tr>`;
  return head + (single ? "" : it.files.map(x => `<tr class="sub">
    <td>${esc(x.name)}</td><td>${esc(x.quant || "–")}</td><td></td>
    <td class="num">${esc(x.downloaded || "")}</td><td class="num">${size(x.size)}</td>
    <td>${usedHtml(x.used_by)}</td><td>${useHtml(x, it.task)} ${deleteHtml(x.path, x.name, x.used_by)}</td></tr>`).join(""));
}

function render() {
  const lib = state.lib;
  $("#libFree").textContent = t("ui.lib.free", { dir: lib.dir, size: size(lib.free) });
  if (!$("#hwLine").textContent) $("#hwLine").textContent = hardwareLine(lib.hardware);
  $("#dls").innerHTML = lib.downloads.map(downloadHtml).join("");
  const head = COLUMNS.map(c => `<th${c === "size" ? ' style="text-align:right"' : ""}>${esc(t("ui.col." + c))}</th>`).join("");
  $("#libTable").innerHTML = `<thead><tr>${head}<th></th></tr></thead><tbody>${lib.items.map(itemHtml).join("")}</tbody>`;
}

async function downloadSelection(repo) {
  const sel = selectedVariants();
  if (!sel.length) return false;
  if (sel.every(i => i.dataset.verdict === "installed")) {
    $("#libMsg").textContent = t("ui.dl.nothing");
    return false;
  }
  const unusable = sel.some(i => ["no", "incompatible", "disk"].includes(i.dataset.verdict));
  if (unusable && !confirm(t("ui.dl.confirm_unusable"))) return false;
  await api("/api/hf/download", { repo, files: sel.flatMap(i => JSON.parse(i.dataset.files)) });
  $("#hfFiles").innerHTML = "";
  return true;
}

function addAsModel(path, task) {
  const name = path.split("/").pop();
  openModelForm(null, { file: state.lib.dir + "/" + path, engine: engineFor(name, state.taskKind[task]), task,
    kind: state.taskKind[task] || "llm", name: name.replace(/\.[^.]+$/, "") });
}

// -> true when the library changed (reload it)
async function onClick(b) {
  const d = b.dataset;
  if (d.install) return void installEngine(d.install, $("#libMsg"));
  if (d.browse) return void browse(d.browse);
  if (d.use) return void addAsModel(d.use, d.task);
  if (d.quick) await api("/api/hf/download", { repo: d.quick, files: JSON.parse(d.files) });
  else if (d.cancel) await api(`/api/hf/cancel/${d.cancel}`, {});
  else if (d.del) {
    if (!confirm(t("ui.lib.delete_confirm", { name: d.label }))) return false;
    await api("/api/library/delete", { path: d.del });
  } else if (b.id === "hfDownload") return downloadSelection(d.repo);
  else return false;
  return true;
}

export function bindLibrary() {
  for (const zone of ["#hfFiles", "#dls", "#libTable"]) {
    $(zone).addEventListener("click", async e => {
      const b = e.target.closest("button");
      if (!b) return;
      $("#libMsg").textContent = "";
      try { if (await onClick(b)) loadLibrary(); } catch (err) { $("#libMsg").textContent = err.message; }
    });
  }
}
