// What the page knows, shared by the views (filled from /api/models, /api/library, /api/status)
export const state = {
  models: {},     // id -> resolved model
  engines: {},    // id -> engine (label, params, file_ext, installed...)
  kinds: {},      // kind -> label
  taskKind: {},   // Hugging Face task -> kind
  lib: null,      // /api/library
  last: null,     // last /api/status
};

// model colour: by position in models.json (no model id hard-coded)
const SEGS = ["var(--seg-1)", "var(--seg-2)", "var(--accent)"];
export function seg(id) {
  const i = Object.keys(state.models).indexOf(id);
  return i < 0 ? "var(--seg-other)" : SEGS[i % SEGS.length];
}
