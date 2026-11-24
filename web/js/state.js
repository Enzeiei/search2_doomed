// [B] Single shared state object + tiny pub/sub. No framework needed.
export const state = {
  results: [],        // Result[] from last search
  activeIndex: -1,    // index into results
  active: null,       // currently previewed Result (may be a neighbour not in results)
  selected: new Set(),// shot_ids selected for AVS
  videoShots: [],     // shots of the active video (neighbour strip)
  videoFilter: null,  // video_id restricting search, or null
  mode: 'kis',        // 'kis' | 'avs'
  submitting: false,  // true while a submit request is in flight
};
const listeners = new Set();
export const subscribe = fn => (listeners.add(fn), () => listeners.delete(fn));
// [B] Call after mutating state; subscribers re-render.
export function emit(){ listeners.forEach(fn => fn(state)); }
