// Small charts of the dashboard

// ponytail: history lives in the page only (~3 min at 2 s polling), resets on reload
const HIST = {};
export function track(key, v) {
  const h = HIST[key] ??= [];
  h.push(v ?? 0);
  if (h.length > 90) h.shift();
  return h;
}

export function spark(el, vals, max, color) {
  if (vals.length < 2) vals = [vals[0], vals[0]];
  const y = v => (40 - Math.min(v / max, 1) * 38).toFixed(1);
  const pts = vals.map((v, i) => `${i / (vals.length - 1) * 100},${y(v)}`);
  el.innerHTML = `<svg class="spark" viewBox="0 0 100 40" preserveAspectRatio="none"${color ? ` style="--c:${color}"` : ""}>
    <path class="a" d="M0,40L${pts.join("L")}L100,40Z"/><path class="l" d="M${pts.join("L")}"/></svg>`;
}

// fill level + colour drifting to red near the limit (model colour < 70 %, orange 70-85 %, red beyond)
export function fill(el, pct) {
  el.style.height = Math.min(pct, 100) + "%";
  el.style.setProperty("--c", pct >= 85 ? "var(--err)" : pct >= 70
    ? `color-mix(in srgb, var(--err) ${(pct - 70) / 15 * 100}%, var(--warn))` : "");
}
