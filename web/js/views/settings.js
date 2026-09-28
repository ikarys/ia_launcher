// Settings view: language, theme and models folder of the launcher (settings.json), inference engines
import { api } from "../api.js";
import { pickFolder } from "../components/folder-picker.js";
import { $, esc } from "../dom.js";
import { settings } from "../i18n.js";
import { themeOptions } from "../theme.js";

async function save(change) {
  $("#setMsg").textContent = "";
  try {
    await api("/api/settings", change);
    location.reload();  // texts and theme are rendered by the server
  } catch (err) { $("#setMsg").textContent = err.message; }
}

export function bindSettings() {
  const folder = $("#setModelsDir").elements.models_dir;
  $("#setLang").innerHTML = Object.entries(settings.langs).map(([code, name]) =>
    `<option value="${esc(code)}"${code === settings.lang ? " selected" : ""}>${esc(name)}</option>`).join("");
  $("#setTheme").innerHTML = themeOptions(settings.theme);
  folder.value = settings.modelsDir;
  $("#setLang").addEventListener("change", e => save({ lang: e.target.value }));
  $("#setTheme").addEventListener("change", e => save({ theme: e.target.value }));
  $("#setModelsDir").addEventListener("submit", e => {
    e.preventDefault();
    save({ models_dir: folder.value });
  });
  $("#setBrowse").addEventListener("click", async () => {
    const chosen = await pickFolder(folder.value);
    if (chosen) { folder.value = chosen; save({ models_dir: chosen }); }
  });
}
