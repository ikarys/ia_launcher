// Tiny event bus: components ask for "reload" (models.json changed) or "poll" (state changed)
// without importing the page's entry point.
const handlers = {};

export const on = (name, fn) => (handlers[name] ??= []).push(fn);

export const emit = (name, ...args) => Promise.all((handlers[name] || []).map(fn => fn(...args)));
