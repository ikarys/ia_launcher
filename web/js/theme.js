// Themes offered in Settings (the chosen one is applied by index.html before the first paint)
import { esc } from "./dom.js";
import { settings, t } from "./i18n.js";

export const themeOptions = selected => settings.themes.map(v =>
  `<option value="${esc(v)}"${v === selected ? " selected" : ""}>${esc(t("ui.theme." + v))}</option>`).join("");
