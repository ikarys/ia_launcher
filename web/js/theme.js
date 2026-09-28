import { $ } from "./dom.js";

// Theme picker of the header, remembered in this browser (applied before paint by index.html)
export function bindThemePicker() {
  const picker = $("#skin"), root = document.documentElement;
  picker.value = root.dataset.skin || "";
  picker.onchange = () => {
    const v = picker.value;
    if (v) root.dataset.skin = v; else delete root.dataset.skin;
    try { localStorage.setItem("skin", v); } catch {}
  };
}
