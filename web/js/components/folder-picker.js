// Pick a folder of the launcher's machine (the browser's own picker can't give a server path)
import { api } from "../api.js";
import { $, esc } from "../dom.js";
import { t } from "../i18n.js";

let current = null, resolveChoice = null;

async function show(path) {
  $("#folderMsg").textContent = "";
  try {
    const d = await api(`/api/folders?path=${encodeURIComponent(path)}`);
    current = d.path;
    $("#folderPath").textContent = d.path;
    $("#folderUp").disabled = !d.parent;
    $("#folderUp").dataset.path = d.parent || "";
    $("#folderShortcuts").innerHTML = d.shortcuts.map(s =>
      `<button type="button" class="link" data-path="${esc(s)}">${esc(s)}</button>`).join("");
    $("#folderList").innerHTML = d.dirs.length
      ? d.dirs.map(name => `<button type="button" data-path="${esc(d.path.replace(/\/$/, "") + "/" + name)}">📁 ${esc(name)}</button>`).join("")
      : `<p class="meta">${esc(t("ui.folder.empty"))}</p>`;
  } catch (err) { $("#folderMsg").textContent = err.message; }
}

function close(choice) {
  $("#folderDlg").close();
  resolveChoice?.(choice);
  resolveChoice = null;
}

// -> the chosen folder, or null when cancelled
export function pickFolder(start) {
  $("#folderDlg").showModal();
  show(start || "~");
  return new Promise(resolve => { resolveChoice = resolve; });
}

export function bindFolderPicker() {
  $("#folderDlg").addEventListener("click", e => {
    const path = e.target.closest("[data-path]")?.dataset.path;
    if (path) show(path);
  });
  $("#folderChoose").addEventListener("click", () => close(current));
  $("#folderCancel").addEventListener("click", () => close(null));
  $("#folderDlg").addEventListener("cancel", () => close(null));  // Esc
}
