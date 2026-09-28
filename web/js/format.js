// Numbers for people: sizes, memory, durations
const dec = x => x.replace(".", ",");

export const gb = mib => mib == null ? "–" : dec((mib / 1024).toFixed(1)) + " Go";

export const size = b => b == null ? "–" : b >= 2 ** 30 ? dec((b / 2 ** 30).toFixed(1)) + " Go"
  : b >= 2 ** 20 ? Math.round(b / 2 ** 20) + " Mo" : Math.max(1, Math.round(b / 1024)) + " Ko";

export function dur(s) {
  if (s == null) return "–";
  if (s < 60) return s + " s";
  if (s < 3600) return Math.floor(s / 60) + " min";
  return Math.floor(s / 3600) + " h " + String(Math.floor(s % 3600 / 60)).padStart(2, "0");
}

export const initials = n => n.split(/[\s\-_.]+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase();
