// Entry point: one page, two views (home: dashboard, /modeles: management)
import { api } from "./api.js";
import { bindEngineCatalog, loadEngines } from "./components/engine-catalog.js";
import { bindHfBrowser } from "./components/hf-browser.js";
import { bindModelForm } from "./components/model-form.js";
import { $ } from "./dom.js";
import { on } from "./events.js";
import { state } from "./state.js";
import { bindThemePicker } from "./theme.js";
import { buildCards, poll } from "./views/dashboard.js";
import { bindLibrary, loadLibrary } from "./views/library.js";
import { bindModelsTable, renderModelsTable } from "./views/models-table.js";

const PAGE = location.pathname === "/modeles" ? "manage" : "home";
const POLL_MS = 2000;

// models.json or engines.json changed: fetch them again and redraw (show: model to display)
async function reloadModels(show) {
  const r = await api("/api/models");
  Object.assign(state, { models: r.models, engines: r.engines, kinds: r.kinds, taskKind: r.task_kind });
  buildCards(show);
  renderModelsTable();
  await poll();
  loadLibrary();
}

on("reload", reloadModels);
on("poll", poll);
bindThemePicker();
bindModelForm();
bindModelsTable();
bindEngineCatalog();
bindHfBrowser();
bindLibrary();
document.body.classList.add("page-" + PAGE);
$("#pageName").textContent = PAGE === "manage" ? "· Gestion des modèles" : "";

await reloadModels();
if (PAGE === "manage") loadEngines();
else setInterval(poll, POLL_MS);
