// Home view: system panel (VRAM, GPU, RAM, CPU) and the model cards, grouped by kind
import { api } from "../api.js";
import { bindCard, cardHtml, updateCard } from "../components/model-card.js";
import { spark, track } from "../components/sparkline.js";
import { $, esc } from "../dom.js";
import { gb } from "../format.js";
import { seg, state } from "../state.js";

let rendered = false;  // first render done: from then on, don't switch the card shown per kind

export function buildCards(show) {
  const byKind = {};
  for (const [id, m] of Object.entries(state.models)) (byKind[m.kind ??= id] ??= []).push(id);
  $("#cards").innerHTML = Object.entries(byKind).map(([kind, ids]) => `
    <div class="kind">
      <div class="kind-head">
        <h3>${esc(state.kinds[kind] || kind)}</h3>
        <select data-kind="${esc(kind)}">${ids.map(id =>
          `<option value="${id}">${esc(state.models[id].name)}</option>`).join("")}</select>
      </div>
      ${ids.map((id, i) => cardHtml(id, state.models[id], i > 0)).join("")}
    </div>`).join("");
  document.querySelectorAll("[data-kind]").forEach(sel =>
    sel.addEventListener("change", () => showModel(sel.dataset.kind, sel.value)));
  Object.keys(state.models).forEach(bindCard);
  rendered = !!show;
  if (show && state.models[show]) showModel(state.models[show].kind, show);
}

function showModel(kind, id) {
  $(`[data-kind="${kind}"]`).value = id;
  for (const [mid, m] of Object.entries(state.models)) if (m.kind === kind) $("#card-" + mid).hidden = mid !== id;
}

function renderSystem(st) {
  const g = st.gpu;
  if (g) {
    $("#gpuName").textContent = "· " + g.name.replace("NVIDIA GeForce ", "");
    $("#vramBig").innerHTML = `${gb(g.used)} <small>/ ${gb(g.total)} · libre ${gb(g.total - g.used)}</small>`;
    const segs = vramSegments(st);
    $("#vramBar").innerHTML = segs.map(([, v, c]) => `<span style="width:${v / g.total * 100}%;background:${c}"></span>`).join("");
    $("#vramLegend").innerHTML = segs.map(([n, v, c]) => `<span><i style="background:${c}"></i>${esc(n)} ${gb(v)}</span>`).join("");
    $("#gpuBig").textContent = g.util != null ? `${g.util} %` : "–";
    spark($("#gpuSpark"), track("gpu", g.util), 100, "var(--seg-1)");
    $("#gpuMeta").innerHTML = [g.temp != null && `<span class="${g.temp >= 83 ? "crit" : g.temp >= 75 ? "hot" : ""}">${g.temp} °C</span>`,
      g.power != null && `${Math.round(g.power)} W`].filter(Boolean).join(" · ");
  } else {
    $("#vramBig").textContent = "nvidia-smi indisponible";
  }
  $("#ramBig").innerHTML = `${gb(st.ram.used_mib)} <small>/ ${gb(st.ram.total_mib)}</small>`;
  spark($("#ramSpark"), track("ram", st.ram.used_mib), st.ram.total_mib, "var(--seg-2)");
  $("#cpuBig").textContent = Math.round(st.cpu.pct) + " %";
  spark($("#cpuSpark"), track("cpu", st.cpu.pct), 100, "var(--ok)");
  $("#cpuMeta").textContent = st.cpu.count + " cœurs logiques";
}

// VRAM bar: display + WSL, then each model, then whatever else uses it
function vramSegments(st) {
  const g = st.gpu;
  const segs = [["Windows + WSL", Math.min(g.baseline, g.used), "var(--seg-other)"]];
  let rest = g.used - segs[0][1];
  for (const [id, s] of Object.entries(st.models)) {
    if (s.vram_mib > 0) {
      const v = Math.min(s.vram_mib, rest);
      segs.push([state.models[id]?.name ?? id, v, seg(id)]);
      rest -= v;
    }
  }
  if (rest > 256) segs.push(["autre", rest, "var(--faint)"]);
  return segs;
}

function render(st) {
  state.last = st;
  renderSystem(st);
  for (const [id, s] of Object.entries(st.models)) {
    const m = state.models[id];
    if (!$("#card-" + id)) continue;  // model removed from the config since the last reload
    updateCard(id, s, st);
    const opt = $(`[data-kind="${m.kind}"] option[value="${id}"]`);
    if (opt) {
      const running = s.pids.length > 0;
      opt.textContent = m.name + (running ? " ●" : "");
      if (!rendered && running) showModel(m.kind, id);
    }
  }
  rendered = true;
}

export async function poll() {
  try {
    const st = await api("/api/status");
    $("#conn").textContent = "à jour " + new Date(st.time * 1000).toLocaleTimeString("fr-FR");
    $("#conn").classList.remove("bad");
    if (st.ready) render(st);
  } catch {
    $("#conn").textContent = "launcher injoignable";
    $("#conn").classList.add("bad");
  }
}
