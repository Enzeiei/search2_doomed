// Shared state + tiny pub/sub.
// An "item" is one result: either a segment from the grid (shot_ids.length >= 1) or a single shot from the strip.
export const state = {
  results: [],          // item[] from the last query
  activeIndex: -1,
  active: null,         // grid item being previewed
  shot: null,           // the single shot currently focused (default: the segment's middle shot, or a strip click)
  selected: new Map(),  // AVS: item.key -> item (persists across queries)
  videoShots: [],       // shots of the active video (neighbour strip)
  videoFilter: null,
  mode: 'kis',          // task mode 'kis' | 'avs'
  submitting: false,
};
const listeners = new Set();
export const subscribe = fn => (listeners.add(fn), () => listeners.delete(fn));
export function emit(){ listeners.forEach(fn => fn(state)); }
