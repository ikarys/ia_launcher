// Entry point: one page, three views (/: dashboard, /models: models, /settings: settings)
import { api } from "./api.js";
import { bindEngineCatalog, loadEngines } from "./components/engine-catalog.js";
import { bindHfBrowser } from "./components/hf-browser.js";
import { bindModelForm } from "./components/model-form.js";
import { on } from "./events.js";
import { state } from "./state.js";
import { bindThemePicker } from "./theme.js";
import { buildCards, poll } from "./views/dashboard.js";
import { bindLibrary, loadLibrary } from "./views/library.js";
import { bindModelsTable, renderModelsTable } from "./views/models-table.js";
import { bindSettings } from "./views/settings.js";

const VIEWS = { "/": "home", "/models": "manage", "/modeles": "manage", "/settings": "settings" };
const VIEW = VIEWS[location.pathname] || "home";
const POLL_MS = 2000;

// models.json or engines.json changed: fetch them again and redraw (show: model to display)
async function reloadModels(show) {
  const r = await api("/api/models");
  Object.assign(state, { models: r.models, engines: r.engines, kinds: r.kinds, taskKind: r.task_kind });
  buildCards(show);
  renderModelsTable();
  await poll();
  loadLibrary();  // shown in /models, and the model form offers its files everywhere
}

on("reload", reloadModels);
on("poll", poll);
bindThemePicker();
bindModelForm();
bindModelsTable();
bindEngineCatalog();
bindHfBrowser();
bindLibrary();
bindSettings();
document.body.classList.add("page-" + VIEW);
document.querySelector(`.nav [data-view="${VIEW}"]`)?.classList.add("on");

await reloadModels();
if (VIEW === "home") setInterval(poll, POLL_MS);
if (VIEW === "settings") loadEngines();
