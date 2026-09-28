// Themes: the launcher's default (Settings) and an optional choice for this browser (header menu)
import { $, esc } from "./dom.js";
import { settings, t } from "./i18n.js";

const SKINS = ["cyber", "pixel", "neo"];  // full themes; "light" / "dark" only force the colours
const KEY = "skin";                        // localStorage: this browser's choice, "" = the default

export function applyTheme(theme) {
  const root = document.documentElement;
  delete root.dataset.skin;
  delete root.dataset.theme;
  if (theme === "light" || theme === "dark") root.dataset.theme = theme;
  else if (SKINS.includes(theme)) root.dataset.skin = theme;
}

export const themeOptions = selected => settings.themes.map(v =>
  `<option value="${esc(v)}"${v === selected ? " selected" : ""}>${esc(t("ui.theme." + v))}</option>`).join("");

export function bindThemePicker() {
  const picker = $("#skin");
  let own = "";
  try { own = localStorage.getItem(KEY) || ""; } catch {}
  picker.innerHTML = `<option value="">${esc(t("ui.theme.default", { name: t("ui.theme." + settings.theme) }))}</option>`
    + themeOptions(own);
  picker.value = own;
  picker.onchange = () => {
    try { localStorage.setItem(KEY, picker.value); } catch {}
    applyTheme(picker.value || settings.theme);
  };
}
