// [B] Two-step submit: request -> confirm bar -> POST -> verdict + history.
import { state, emit } from './state.js';
import * as api from './api.js';
import * as history from './history.js';
import { refresh } from './grid.js';

const $ = id => document.getElementById(id);
let pending = null;

// [B] Step 1: show the confirm bar. Enter confirms, Esc cancels (wired in main.js).
export function requestSubmit(){
  if (state.submitting) return;
  const shots = state.mode === 'avs' && state.selected.size
    ? state.results.filter(r => state.selected.has(r.shot_id))
    : (state.active ? [state.active] : []);
  if (!shots.length) return;
  pending = shots;
  const s = shots[0];
  $('confirm').hidden = false;
  $('confirm').textContent = shots.length === 1
    ? `Submit video ${s.video_id}, shot ${s.n} (${(s.start_ms/1000).toFixed(1)}-${(s.end_ms/1000).toFixed(1)} s)? Enter = yes, Esc = no`
    : `Submit ${shots.length} selected shots? Enter = yes, Esc = no`;
}
export const isConfirming = () => pending !== null;
export function cancel(){ pending = null; $('confirm').hidden = true; }

// [B] Step 2: send one by one (per-item status, no opaque batch). Button locked while in flight.
export async function confirm(){
  if (!pending || state.submitting) return;
  const shots = pending; cancel();
  state.submitting = true; $('btn-submit').disabled = true;
  const tally = { CORRECT: 0, WRONG: 0, OTHER: 0 };
  for (const s of shots){
    const res = await api.submit({ video_id: s.video_id, start_ms: s.start_ms, end_ms: s.end_ms });
    const { verdict, message } = normalise(res);
    history.add({ shot_id: s.shot_id, video_id: s.video_id, n: s.n,
                  start_ms: s.start_ms, end_ms: s.end_ms, verdict, message });
    tally[verdict] !== undefined ? tally[verdict]++ : tally.OTHER++;
    showVerdict(verdict, message, shots.length > 1 ? tally : null);
  }
  state.submitting = false; $('btn-submit').disabled = false;
  state.selected.clear();
  refresh(); emit();
}

// [B] Accepts either the flattened shape we asked Partner A for ({verdict, message}) or the raw
// shape dres_client.py returns today ({http_status, accepted, response:{...}}).
// [A] ASSUMPTION about DRES v2 (verify on the practice server): response.submission holds
// CORRECT/WRONG/INDETERMINATE/UNDECIDABLE and response.description holds the text; 412 = no active task.
function normalise(res){
  if (res.error) return { verdict: 'ERROR', message: res.error };
  if (res.verdict) return { verdict: res.verdict, message: res.message || '' };
  const raw = res.response || {};
  if (res.accepted === false || (res.http_status && res.http_status >= 400)){
    const hint = res.http_status === 412 ? 'No active task. ' : '';
    return { verdict: 'ERROR', message: `${hint}HTTP ${res.http_status} ${raw.description || raw.raw || ''}`.trim() };
  }
  return { verdict: raw.submission || 'ERROR', message: raw.description || '' };
}

// [B] Big verdict box; colour = CSS class = verdict. Raw DRES text is always shown.
function showVerdict(verdict, message, tally){
  const el = $('verdict');
  el.hidden = false; el.className = verdict;
  const icon = { CORRECT:'✔', WRONG:'✘' }[verdict] || '!';
  el.textContent = `${icon} ${verdict} ${message}` +
    (tally ? ` (${tally.CORRECT} correct / ${tally.WRONG} wrong)` : '');
}
